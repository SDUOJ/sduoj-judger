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

import static org.junit.Assert.*;

import com.sduoj.common.util.JsonUtils;
import com.sduoj.judger.handler.CasesRunHandler;
import com.sduoj.sandbox.dto.SandboxResultDTO;

import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Run as Linux root in the actual worker image; ordinary desktop builds skip explicitly. */
public class HelperCompilationTest {
    private Path temporary;
    private Path parent;
    private RunWorkspace first;
    private RunWorkspace second;

    @Before
    public void setup() throws Exception {
        Assume.assumeTrue("Linux required", System.getProperty("os.name").equals("Linux"));
        temporary = Files.createTempDirectory("helper-compilation-test-");
        Assume.assumeTrue("root worker required",
                Integer.valueOf(0).equals(Files.getAttribute(temporary, "unix:uid")));
        Files.setPosixFilePermissions(temporary, PosixFilePermissions.fromString("rwxr-xr-x"));
        parent = Files.createDirectory(temporary.resolve("workspace"));
        Files.setPosixFilePermissions(parent, PosixFilePermissions.fromString("rwx--x--x"));
        first = RunWorkspace.create(parent, 42, 1);
        second = RunWorkspace.create(parent, 43, 1);
    }

    @After
    public void cleanup() throws Exception {
        if (temporary != null) WorkspaceFiles.delete(temporary);
    }

    private Process startAs(int uid, Path cwd, String... command) throws Exception {
        List<String> argv = new ArrayList<>(List.of("python3", "-c",
                "import os,sys; uid=int(sys.argv[1]); os.setgroups([]); os.setgid(uid); os.setuid(uid); os.execvp(sys.argv[2],sys.argv[2:])",
                Integer.toString(uid)));
        argv.addAll(List.of(command));
        return new ProcessBuilder(argv).directory(cwd.toFile()).redirectErrorStream(true).start();
    }

    private String succeeds(Process process) throws Exception {
        assertTrue("process deadline", process.waitFor(15, TimeUnit.SECONDS));
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        assertEquals(output, 0, process.exitValue());
        return output;
    }

    private void denied(int uid, Path path) throws Exception {
        var process = startAs(uid, temporary, "sh", "-c", "printf changed > \"$1\"", "fixture", path.toString());
        assertTrue(process.waitFor(5, TimeUnit.SECONDS));
        assertNotEquals(0, process.exitValue());
    }

    private Path lease(int uid) {
        return parent.resolve(".helper-uids").resolve(Integer.toString(uid));
    }

    @Test
    public void identitiesAreExclusiveAcrossTasksAndOnlyTheirOwnerCanWriteBuilds() throws Exception {
        try (var a = HelperCompilation.create(first.root()); var b = HelperCompilation.create(second.root())) {
            assertNotEquals(0, a.uid());
            assertNotEquals(65534, a.uid());
            assertNotEquals(a.uid(), b.uid());
            a.allowWrites();
            b.allowWrites();
            assertEquals(PosixFilePermissions.fromString("rwx------"), Files.getPosixFilePermissions(a.build()));
            succeeds(startAs(a.uid(), a.build(), "sh", "-c", "printf own > own"));
            denied(65534, a.build().resolve("own"));
            denied(b.uid(), a.build().resolve("own"));
            assertEquals("own", Files.readString(a.build().resolve("own")));
        }
    }

    @Test
    public void skipsAnIdentityWithAnExistingProcessEvenWithoutALease() throws Exception {
        var process = startAs(200000, temporary, "sleep", "30");
        try {
            // Wait for the credential transition rather than racing the root launcher startup.
            for (int i = 0; i < 100 && !Files.readString(Path.of("/proc", Long.toString(process.pid()), "status"))
                    .contains("Uid:\t200000\t"); i++) Thread.sleep(10);
            assertTrue(process.isAlive());
            assertTrue(Files.readString(Path.of("/proc", Long.toString(process.pid()), "status"))
                    .contains("Uid:\t200000\t"));
            try (var helper = HelperCompilation.create(first.root())) {
                assertNotEquals(200000, helper.uid());
            }
            assertTrue("foreign process must not be killed", process.isAlive());
        } finally {
            process.destroyForcibly();
            assertTrue(process.waitFor(5, TimeUnit.SECONDS));
        }
    }

    @Test
    public void freshRuntimeInodesCannotBeChangedThroughAnOldWritableDescriptorOrByNobody() throws Exception {
        try (var helper = HelperCompilation.create(first.root())) {
            helper.allowWrites();
            succeeds(startAs(helper.uid(), helper.build(), "sh", "-c", "printf original > main"));
            Path original = helper.build().resolve("main");
            Object oldKey = Files.readAttributes(original, BasicFileAttributes.class).fileKey();
            try (var retained = FileChannel.open(original, StandardOpenOption.WRITE)) {
                helper.sealTo(first.checker());
                retained.write(ByteBuffer.wrap("modified".getBytes(StandardCharsets.UTF_8)), 0);
                Path sealed = first.checker().resolve("main");
                assertNotEquals(oldKey, Files.readAttributes(sealed, BasicFileAttributes.class).fileKey());
                assertEquals(0, Files.getAttribute(sealed, "unix:uid"));
                assertEquals("original", Files.readString(sealed));
                denied(65534, sealed);
                denied(helper.uid(), sealed);
                assertEquals("original", Files.readString(sealed));
            }
        }
    }

    @Test
    public void nestedZipSourcesCompileAndTheSealedProgramRunsAsNobody() throws Exception {
        try (var helper = HelperCompilation.create(first.root())) {
            var archive = new ByteArrayOutputStream();
            try (var zip = new ZipOutputStream(archive)) {
                zip.putNextEntry(new ZipEntry("src/main.cc"));
                zip.write("#include <cstdio>\nint main(){puts(\"helper-ok\");}\n".getBytes(StandardCharsets.UTF_8));
                zip.closeEntry();
            }
            CasesRunHandler.extractZip(archive.toByteArray(), helper.build());
            helper.allowWrites();
            Path out = first.output("helper.compile.out");
            Path err = first.output("helper.compile.err");
            String json = succeeds(new ProcessBuilder("/usr/bin/sandbox",
                    "--uid=" + helper.uid(), "--gid=" + helper.uid(),
                    "--exe_path=/opt/gcc/13.2.0/bin/g++", "--exe_args=src/main.cc",
                    "--exe_args=-static", "--exe_args=-o", "--exe_args=src/main",
                    "--max_cpu_time=10000", "--max_real_time=15000", "--max_memory=536870912",
                    "--max_stack=134217728", "--max_output_size=16777216", "--input_path=/dev/null",
                    "--output_path=" + out, "--error_path=" + err,
                    "--exe_envs=PATH=" + System.getenv("PATH"))
                    .directory(helper.build().toFile()).redirectErrorStream(true).start());
            var compiled = JsonUtils.toObject(json, SandboxResultDTO.class);
            assertEquals(Files.readString(err), 0, compiled.getResult());
            assertEquals(Files.readString(err), 0, compiled.getExitCode());
            helper.sealTo(first.validator());
            assertEquals("helper-ok\n", succeeds(startAs(65534, first.validator(), "./src/main")));
            assertEquals(0, Files.getAttribute(first.validator().resolve("src"), "unix:uid"));
            denied(65534, first.validator().resolve("src/main"));
        }
    }

    @Test
    public void exitAndExceptionCleanupKillsReparentedChildrenBeforeReleasingIdentity() throws Exception {
        int uid;
        Path build;
        long child;
        try (var helper = HelperCompilation.create(first.root())) {
            uid = helper.uid();
            build = helper.build();
            helper.allowWrites();
            succeeds(startAs(uid, build, "sh", "-c",
                    "sleep 30 </dev/null >/dev/null 2>&1 & echo $! > child"));
            child = Long.parseLong(Files.readString(build.resolve("child")).trim());
            assertTrue(ProcessHandle.of(child).orElseThrow().isAlive());
        }
        assertTrue(ProcessHandle.of(child).isEmpty() || !ProcessHandle.of(child).orElseThrow().isAlive());
        assertFalse(Files.exists(build, LinkOption.NOFOLLOW_LINKS));
        assertFalse(Files.exists(lease(uid), LinkOption.NOFOLLOW_LINKS));
        try {
            try (var helper = HelperCompilation.create(second.root())) {
                helper.allowWrites();
                succeeds(startAs(helper.uid(), helper.build(), "sh", "-c", "printf partial > output"));
                throw new IOException("compile failed fixture");
            }
        } catch (IOException expected) {
            assertEquals("compile failed fixture", expected.getMessage());
        }
        try (var paths = Files.newDirectoryStream(second.root(), "helper-build-*")) {
            assertFalse(paths.iterator().hasNext());
        }
    }

    @Test
    public void anUnreapedProcessQuarantinesTheLeaseUntilAbsenceCanBeProved() throws Exception {
        var helper = HelperCompilation.create(first.root());
        helper.allowWrites();
        Path ready = temporary.resolve("child.pid");
        Path release = temporary.resolve("release-parent");
        var parent = new ProcessBuilder("python3", "-c",
                "import os,sys,time\n"
                        + "pid=os.fork()\n"
                        + "if pid==0:\n"
                        + " uid=int(sys.argv[1]); os.setgroups([]); os.setgid(uid); os.setuid(uid); os.execl('/bin/sleep','sleep','30')\n"
                        + "open(sys.argv[2],'w').write(str(pid))\n"
                        + "while not os.path.exists(sys.argv[3]): time.sleep(.01)\n"
                        + "os.waitpid(pid,0)\n",
                Integer.toString(helper.uid()), ready.toString(), release.toString()).start();
        try {
            for (int i = 0; i < 100 && !Files.exists(ready); i++) Thread.sleep(10);
            long child = Long.parseLong(Files.readString(ready));
            Path status = Path.of("/proc", Long.toString(child), "status");
            for (int i = 0; i < 100 && !Files.readString(status)
                    .contains("Uid:\t" + helper.uid() + "\t"); i++) Thread.sleep(10);
            assertTrue(Files.readString(status).contains("Uid:\t" + helper.uid() + "\t"));
            IOException failure = assertThrows(IOException.class, () -> helper.sealTo(first.checker()));
            assertTrue(failure.getMessage().contains("quarantined"));
            assertTrue(Files.exists(lease(helper.uid()), LinkOption.NOFOLLOW_LINKS));
            assertTrue(Files.exists(helper.build(), LinkOption.NOFOLLOW_LINKS));
            try (var runtime = Files.newDirectoryStream(first.checker())) {
                assertFalse("no runtime file may be published", runtime.iterator().hasNext());
            }
            try (var next = HelperCompilation.create(second.root())) {
                assertNotEquals(helper.uid(), next.uid());
            }
        } finally {
            Files.writeString(release, "reap");
            succeeds(parent);
            helper.close();
        }
        assertFalse(Files.exists(lease(helper.uid()), LinkOption.NOFOLLOW_LINKS));
    }

    @Test
    public void sealingRejectsLinksSpecialFilesAndOversizedTrees() throws Exception {
        for (String fixture : new String[] {"link", "hardlink", "fifo", "large"}) {
            try (var helper = HelperCompilation.create(first.root())) {
                helper.allowWrites();
                switch (fixture) {
                    case "link" -> Files.createSymbolicLink(helper.build().resolve("output"), Path.of("/etc/passwd"));
                    case "hardlink" -> Files.createLink(helper.build().resolve("output"),
                            Files.writeString(temporary.resolve("external"), "unchanged"));
                    case "fifo" -> succeeds(new ProcessBuilder("mkfifo", helper.build().resolve("output").toString()).start());
                    case "large" -> {
                        try (var channel = FileChannel.open(helper.build().resolve("output"),
                                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
                            channel.write(ByteBuffer.wrap(new byte[] {1}), 64L * 1024 * 1024);
                        }
                    }
                    default -> throw new AssertionError();
                }
                assertThrows(IOException.class, () -> helper.sealTo(first.checker()));
                assertFalse(Files.exists(first.checker().resolve("output"), LinkOption.NOFOLLOW_LINKS));
            }
        }
    }

    @Test
    public void crashLeasesAndOtherPidNamespacesAreNeverReused() throws Exception {
        try (var helper = HelperCompilation.create(first.root())) {
            Path pool = lease(helper.uid()).getParent();
            Files.createDirectory(pool.resolve(Integer.toString(helper.uid() + 1)));
            try (var other = HelperCompilation.create(second.root())) {
                assertNotEquals(helper.uid() + 1, other.uid());
            }
            Files.writeString(pool.resolve("namespace"), "different-namespace");
            assertThrows(IOException.class, () -> HelperCompilation.create(second.root()));
        }
    }
}
