/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.util;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.SeekableByteChannel;
import java.nio.file.DirectoryStream;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.SecureDirectoryStream;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributeView;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * Compile task-supplied helpers under an exclusive identity, then publish fresh root-owned files.
 * Workers in one visible PID namespace must share the canonical /workspace lease pool and reserve
 * UIDs/GIDs 200000..204095 for these helpers. Independent pools in that namespace are unsupported.
 * Leases left by crashes/failed cleanup are never reclaimed automatically; a boot/namespace change
 * also fails closed until an operator verifies that no previous helper can still access the files.
 */
public final class HelperCompilation implements AutoCloseable {
    private static final int FIRST_UID = 200000;
    private static final int UID_COUNT = 4096;
    private static final int MAX_ENTRIES = 1024;
    private static final long MAX_BYTES = 64L * 1024 * 1024;
    private static final Set<PosixFilePermission> PRIVATE =
            PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> SEALED =
            PosixFilePermissions.fromString("rwxr-xr-x");
    private final Path lease;
    private final Path build;
    private final int uid;
    private boolean writable;
    private boolean closed;

    private HelperCompilation(Path lease, Path build, int uid) {
        this.lease = lease;
        this.build = build;
        this.uid = uid;
    }

    public static HelperCompilation create(Path task) throws IOException {
        requireProtectedRoot(task);
        requireProtectedRoot(task.getParent());
        Path pool = task.getParent().resolve(".helper-uids");
        try {
            Files.createDirectory(pool, PosixFilePermissions.asFileAttribute(PRIVATE));
        } catch (FileAlreadyExistsException existing) {
            // Shared by all workers using this workspace, including other JVMs.
        }
        requireProtectedRoot(pool);
        if (!Files.getPosixFilePermissions(pool, LinkOption.NOFOLLOW_LINKS).equals(PRIVATE)) {
            throw new IOException("Helper lease pool must be private");
        }
        requireProcessNamespace(pool);
        for (int uid = FIRST_UID; uid < FIRST_UID + UID_COUNT; uid++) {
            Path lease = pool.resolve(Integer.toString(uid));
            try {
                Files.createDirectory(lease, PosixFilePermissions.asFileAttribute(PRIVATE));
            } catch (FileAlreadyExistsException occupied) {
                continue;
            }
            // Reserve atomically before checking processes. Never reuse crash leftovers.
            // A scan failure deliberately leaves this lease quarantined: absence is unproven.
            if (!processes(uid).isEmpty()) {
                Files.delete(lease);
                continue;
            }
            try {
                Path build = Files.createTempDirectory(task, "helper-build-",
                        PosixFilePermissions.asFileAttribute(PRIVATE));
                return new HelperCompilation(lease, build, uid);
            } catch (IOException failure) {
                Files.delete(lease);
                throw failure;
            }
        }
        throw new IOException("No exclusive helper compilation identity available");
    }

    public Path build() { return build; }
    public int uid() { return uid; }

    /** Source preparation finishes as root before the compiler can change any directory. */
    public void allowWrites() throws IOException {
        if (writable || closed) throw new IOException("Helper build already opened");
        try (var paths = Files.walk(build)) {
            var entries = paths.sorted(Comparator.comparingInt(Path::getNameCount).reversed()).toList();
            if (entries.size() > MAX_ENTRIES) throw new IOException("Too many helper source entries");
            for (Path path : entries) {
                var attributes = Files.readAttributes(path,
                        java.nio.file.attribute.BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                if (!attributes.isDirectory() && !attributes.isRegularFile()) {
                    throw new IOException("Helper source contains a link or special file");
                }
                if (attributes.isDirectory()) {
                    Files.setAttribute(path, "unix:gid", uid, LinkOption.NOFOLLOW_LINKS);
                    Files.setAttribute(path, "unix:uid", uid, LinkOption.NOFOLLOW_LINKS);
                    Files.setPosixFilePermissions(path, PRIVATE);
                }
            }
        }
        writable = true;
    }

    /** No compiler may retain a writer while root creates the immutable runtime copy. */
    public void sealTo(Path destination) throws IOException {
        if (!writable || closed) throw new IOException("Helper build is not open");
        quiesce();
        requireProtectedRoot(destination);
        try (var existing = Files.newDirectoryStream(destination)) {
            if (existing.iterator().hasNext()) throw new IOException("Helper destination is not empty");
        }
        try (DirectoryStream<Path> parent = Files.newDirectoryStream(build.getParent())) {
            if (!(parent instanceof SecureDirectoryStream<?>)) {
                throw new IOException("Secure helper directory operations unavailable");
            }
            @SuppressWarnings("unchecked")
            var secure = (SecureDirectoryStream<Path>) parent;
            try (var source = secure.newDirectoryStream(build.getFileName(), LinkOption.NOFOLLOW_LINKS)) {
                copy(source, build, destination, 0, new long[2]);
            }
        }
    }

    private static void copy(SecureDirectoryStream<Path> source, Path sourcePath, Path destination, int depth,
            long[] budget) throws IOException {
        if (depth > 32) throw new IOException("Helper output tree too deep");
        for (Path entry : source) {
            if (++budget[0] > MAX_ENTRIES) throw new IOException("Too many helper output entries");
            Path name = entry.getFileName();
            var attributes = source.getFileAttributeView(name, BasicFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS).readAttributes();
            Path target = destination.resolve(name.toString());
            if (attributes.isDirectory()) {
                Files.createDirectory(target, PosixFilePermissions.asFileAttribute(SEALED));
                try (var child = source.newDirectoryStream(name, LinkOption.NOFOLLOW_LINKS)) {
                    copy(child, sourcePath.resolve(name.toString()), target, depth + 1, budget);
                }
            } else if (attributes.isRegularFile()) {
                // Only this lease could mutate these directories, and quiesce proved it gone.
                // Reject aliases to external writable inodes as well as symbolic links.
                if (((Number) Files.getAttribute(sourcePath.resolve(name.toString()),
                        "unix:nlink", LinkOption.NOFOLLOW_LINKS)).longValue() != 1) {
                    throw new IOException("Helper output is a hard link");
                }
                if (attributes.size() > MAX_BYTES - budget[1]) {
                    throw new IOException("Helper outputs exceed byte limit");
                }
                // CREATE_NEW creates a new root-owned inode, never chowns an untrusted inode.
                try (var input = source.newByteChannel(name,
                        Set.of(StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS));
                        var output = Files.newByteChannel(target,
                                Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                                        LinkOption.NOFOLLOW_LINKS),
                                PosixFilePermissions.asFileAttribute(SEALED))) {
                    copyBytes(input, output, budget);
                }
            } else {
                throw new IOException("Helper output contains a link or special file");
            }
        }
    }

    private static void copyBytes(SeekableByteChannel input, SeekableByteChannel output,
            long[] budget) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(8192);
        while (input.read(buffer) != -1) {
            budget[1] += buffer.position();
            if (budget[1] > MAX_BYTES) throw new IOException("Helper outputs exceed byte limit");
            buffer.flip();
            while (buffer.hasRemaining()) output.write(buffer);
            buffer.clear();
        }
    }

    private void quiesce() throws IOException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        int emptyScans = 0;
        while (true) {
            List<CompilerProcess> remaining = processes(uid);
            if (remaining.isEmpty()) {
                if (++emptyScans == 2) return;
            } else {
                emptyScans = 0;
            }
            // ProcessHandle retains PID/start-time identity, avoiding a kill of a reused PID.
            remaining.forEach(process -> {
                if (process.handle() != null) process.handle().destroyForcibly();
            });
            if (System.nanoTime() >= deadline) {
                throw new IOException("Helper processes remain; identity lease quarantined");
            }
            try {
                Thread.sleep(20);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IOException("Helper cleanup interrupted; identity lease quarantined", interrupted);
            }
        }
    }

    private record CompilerProcess(ProcessHandle handle) {}

    private static List<CompilerProcess> processes(int uid) throws IOException {
        List<CompilerProcess> result = new ArrayList<>();
        try (var entries = Files.newDirectoryStream(Path.of("/proc"))) {
            int count = 0;
            for (Path entry : entries) {
                String name = entry.getFileName().toString();
                if (!name.matches("[1-9][0-9]*")) continue;
                if (++count > 65536) throw new IOException("Process scan exceeds limit");
                try {
                    // Obtain the handle before credentials, so its native start-time check also
                    // covers exit/reuse races between reading status and sending SIGKILL.
                    var handle = ProcessHandle.of(Long.parseLong(name));
                    String status;
                    try (var input = Files.newInputStream(entry.resolve("status"), LinkOption.NOFOLLOW_LINKS)) {
                        byte[] bytes = input.readNBytes(1024 * 1024 + 1);
                        if (bytes.length > 1024 * 1024) throw new IOException("Process status exceeds limit");
                        status = new String(bytes, java.nio.charset.StandardCharsets.US_ASCII);
                    }
                    boolean uidSeen = false, gidSeen = false, groupsSeen = false, matches = false;
                    for (String line : status.split("\n")) {
                        if (line.startsWith("Uid:") || line.startsWith("Gid:") || line.startsWith("Groups:")) {
                            uidSeen |= line.startsWith("Uid:");
                            gidSeen |= line.startsWith("Gid:");
                            groupsSeen |= line.startsWith("Groups:");
                            for (String number : line.substring(line.indexOf(':') + 1).trim().split("\\s+")) {
                                if (!number.isEmpty() && Long.parseLong(number) == uid) matches = true;
                            }
                        }
                    }
                    if (!uidSeen || !gidSeen || !groupsSeen) throw new IOException("Incomplete process credentials");
                    // A missing Java handle is not proof of absence: a dead thread-group
                    // leader can still have live threads. Retain the identity until /proc
                    // itself no longer reports it (including unreaped zombies).
                    if (matches) result.add(new CompilerProcess(handle.orElse(null)));
                } catch (NoSuchFileException exited) {
                    // A vanished status file proves this PID has exited; a later PID is scanned
                    // on the next pass if it belongs to this still-reserved identity.
                }
            }
        }
        return result;
    }

    private static void requireProcessNamespace(Path pool) throws IOException {
        String identity = Files.readString(Path.of("/proc/sys/kernel/random/boot_id")).trim()
                + ":" + Files.readSymbolicLink(Path.of("/proc/self/ns/pid"));
        Path marker = pool.resolve("namespace");
        try {
            Files.writeString(marker, identity, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS);
            Files.setPosixFilePermissions(marker, PosixFilePermissions.fromString("rw-------"));
        } catch (FileAlreadyExistsException existing) {
            // A crash/partial marker or another PID namespace fails closed, not automatic reuse.
        }
        if (!Files.isRegularFile(marker, LinkOption.NOFOLLOW_LINKS)
                || !Integer.valueOf(0).equals(Files.getAttribute(marker, "unix:uid", LinkOption.NOFOLLOW_LINKS))
                || !identity.equals(Files.readString(marker))) {
            throw new IOException("Helper lease pool requires the same boot and visible PID namespace");
        }
    }

    private static void requireProtectedRoot(Path path) throws IOException {
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)
                || !Integer.valueOf(0).equals(Files.getAttribute(path, "unix:uid", LinkOption.NOFOLLOW_LINKS))) {
            throw new IOException("Helper parent must be a real root-owned directory");
        }
        var permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        if (permissions.contains(PosixFilePermission.GROUP_WRITE)
                || permissions.contains(PosixFilePermission.OTHERS_WRITE)) {
            throw new IOException("Helper parent must not be writable by untrusted identities");
        }
    }

    @Override
    public void close() throws IOException {
        if (closed) return;
        quiesce();
        WorkspaceFiles.delete(build);
        Files.delete(lease);
        closed = true;
    }
}
