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
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;

/** Keep paths opened by root outside every directory writable by the submitted program. */
public final class RunWorkspace {
    private final Path root;
    private final Path program;
    private final Path io;
    private final Path checker;
    private final Path validator;

    private RunWorkspace(Path root) throws IOException {
        this.root = root;
        program = directory(root.resolve("program"), "rwxr-xr-x");
        io = directory(root.resolve("io"), "rwx--x--x");
        checker = directory(root.resolve("checker"), "rwxr-xr-x");
        validator = directory(root.resolve("validator"), "rwxr-xr-x");
    }

    public static RunWorkspace create(Path parent, long id, int version) throws IOException {
        if (id <= 0 || version <= 0) throw new IllegalArgumentException("Invalid Run identity");
        Path base = parent.toAbsolutePath().normalize();
        requireDirectory(base);
        requireProtected(base);
        Path root = directory(base.resolve("run-" + id + "-" + version), "rwx--x--x");
        try {
            return new RunWorkspace(root);
        } catch (IOException | RuntimeException failure) {
            // Nothing untrusted has executed, and all entries were created by this invocation.
            for (String child : new String[] {"program", "io", "checker", "validator"}) {
                Files.deleteIfExists(root.resolve(child));
            }
            Files.delete(root);
            throw failure;
        }
    }

    /** The deployed worker runs as root; fail closed if that assumption or parent policy changes. */
    public void requireRootOwner() throws IOException {
        for (Path path : new Path[] {root.getParent(), root, program, io, checker, validator}) {
            requireDirectory(path);
            if (!Integer.valueOf(0).equals(Files.getAttribute(path, "unix:uid", LinkOption.NOFOLLOW_LINKS))) {
                throw new IOException("Run workspaces must be owned by root");
            }
            requireProtected(path);
        }
    }

    public Path root() { return root; }
    public Path program() { return program; }
    public Path checker() { return checker; }
    public Path validator() { return validator; }

    public void allowProgramWrites() throws IOException {
        requireDirectory(program);
        // Snapshot before opening any parent for writes. Nested sources (for
        // example javac src/Main.java) also need adjacent compiler outputs.
        try (var paths = Files.walk(program)) {
            var directories = paths.filter(path -> Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS))
                    .sorted(java.util.Comparator.comparingInt(Path::getNameCount).reversed()).toList();
            for (Path directory : directories) {
                requireDirectory(directory);
                Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwxrwxrwx"));
            }
        }
    }

    public Path input(String name, byte[] bytes) throws IOException {
        Path path = ioPath(name);
        writeNew(path, bytes);
        return path;
    }

    public Path output(String name) throws IOException {
        return input(name, new byte[0]);
    }

    /** Checkers open their report themselves after dropping privileges. Parent stays immutable. */
    public Path report(String name) throws IOException {
        Path path = output(name);
        Files.setPosixFilePermissions(path, PosixFilePermissions.fromString("rw-rw-rw-"));
        return path;
    }

    public Path ioPath(String name) throws IOException {
        if (!name.matches("[A-Za-z0-9_.-]+") || name.equals(".") || name.equals("..")) {
            throw new IllegalArgumentException("Invalid Run IO name");
        }
        requireDirectory(io);
        return io.resolve(name);
    }

    public static Path source(Path directory, String name) throws IOException {
        Path base = directory.toAbsolutePath().normalize();
        Path path = base.resolve(name).normalize();
        if (Path.of(name).isAbsolute() || !path.startsWith(base) || path.equals(base)) {
            throw new IllegalArgumentException("Unsafe Run source path");
        }
        ensureParents(base, path.getParent());
        if (Files.isSymbolicLink(path)) throw new IOException("Run source is a link");
        return path;
    }

    public static void ensureParents(Path directory, Path target) throws IOException {
        if (!target.startsWith(directory)) throw new IllegalArgumentException("Unsafe Run parent");
        requireDirectory(directory);
        Path path = directory;
        for (Path component : directory.relativize(target)) {
            path = path.resolve(component);
            if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
                directory(path, "rwxr-xr-x");
            }
            requireDirectory(path);
        }
    }

    public static void writeNew(Path path, byte[] bytes) throws IOException {
        Files.write(path, bytes, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                LinkOption.NOFOLLOW_LINKS);
        Files.setPosixFilePermissions(path, PosixFilePermissions.fromString("rw-r--r--"));
    }

    public static byte[] read(Path path, int limit) throws IOException {
        var attributes = attributes(path);
        if (!attributes.isRegularFile() || attributes.size() > limit) {
            throw new IOException("Run output is not a bounded regular file");
        }
        try (var input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(limit + 1);
            if (bytes.length > limit) throw new IOException("Run output exceeds limit");
            return bytes;
        }
    }

    public static long size(Path path) throws IOException {
        var attributes = attributes(path);
        if (!attributes.isRegularFile()) throw new IOException("Run output is not a regular file");
        return attributes.size();
    }

    public static void copyPrefix(Path source, Path target, int limit) throws IOException {
        if (!attributes(source).isRegularFile()) throw new IOException("Run log is not a regular file");
        byte[] bytes;
        try (var input = Files.newInputStream(source, LinkOption.NOFOLLOW_LINKS)) {
            bytes = input.readNBytes(limit);
        }
        Files.write(target, bytes, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING,
                LinkOption.NOFOLLOW_LINKS);
    }

    private static BasicFileAttributes attributes(Path path) throws IOException {
        return Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
    }

    private static Path directory(Path path, String mode) throws IOException {
        Files.createDirectory(path,
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString(mode)));
        Files.setPosixFilePermissions(path, PosixFilePermissions.fromString(mode));
        return path;
    }

    private static void requireDirectory(Path path) throws IOException {
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Run parent is not a real directory");
        }
    }

    private static void requireProtected(Path path) throws IOException {
        var permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        if (permissions.contains(java.nio.file.attribute.PosixFilePermission.GROUP_WRITE)
                || permissions.contains(java.nio.file.attribute.PosixFilePermission.OTHERS_WRITE)) {
            throw new IOException("Run parent and trusted directories must not be writable by programs");
        }
    }
}
