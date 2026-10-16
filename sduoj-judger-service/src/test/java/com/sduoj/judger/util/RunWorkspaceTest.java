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

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import com.sduoj.judger.handler.CasesRunHandler;

import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Comparator;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class RunWorkspaceTest {
    private Path temporary;
    private Path parent;
    private RunWorkspace task;

    @Before
    public void setup() throws Exception {
        temporary = Files.createTempDirectory("run-workspace-test-");
        Files.setPosixFilePermissions(temporary, PosixFilePermissions.fromString("rwxr-xr-x"));
        parent = Files.createDirectory(temporary.resolve("workspace"));
        Files.setPosixFilePermissions(parent, PosixFilePermissions.fromString("rwx--x--x"));
        task = RunWorkspace.create(parent, 42, 1);
    }

    @After
    public void cleanup() throws Exception {
        try (var paths = Files.walk(temporary)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                Files.deleteIfExists(path);
            }
        }
    }

    @Test
    public void programNamesCannotRedirectTheInputsOrOutputsOfLaterCases() throws Exception {
        task.allowProgramWrites();
        Path marker = Files.writeString(temporary.resolve("marker"), "unchanged");
        Files.createSymbolicLink(task.program().resolve("1.in"), marker);
        Files.createSymbolicLink(task.program().resolve("1.out"), marker);
        Path input = task.input("1.in", "fixture input".getBytes(StandardCharsets.UTF_8));
        Path output = task.output("1.out");
        assertEquals("fixture input", Files.readString(input));
        assertEquals(0, Files.size(output));
        assertEquals("unchanged", Files.readString(marker));
        assertFalse(input.startsWith(task.program()));
        assertFalse(output.startsWith(task.program()));
    }

    @Test
    public void protectedParentsAndExclusiveFilesStayOutsideTheWritableProgramTree() throws Exception {
        task.allowProgramWrites();
        for (Path path : new Path[] {task.root(), task.checker(), task.validator(),
                task.ioPath("probe").getParent()}) {
            var mode = Files.getPosixFilePermissions(path);
            assertFalse(mode.contains(java.nio.file.attribute.PosixFilePermission.GROUP_WRITE));
            assertFalse(mode.contains(java.nio.file.attribute.PosixFilePermission.OTHERS_WRITE));
        }
        Path input = task.input("0.in", new byte[] {1});
        assertThrows(java.nio.file.FileAlreadyExistsException.class,
                () -> task.input("0.in", new byte[] {2}));
        assertArrayEquals(new byte[] {1}, Files.readAllBytes(input));
        assertThrows(IllegalArgumentException.class, () -> task.ioPath("../outside"));
        assertThrows(IllegalArgumentException.class, () -> task.ioPath("."));
    }

    @Test
    public void sourcePathsAndZipParentsRejectLinksAndTraversal() throws Exception {
        Path outside = Files.createDirectory(temporary.resolve("outside"));
        Files.createSymbolicLink(task.program().resolve("alias"), outside);
        assertThrows(java.io.IOException.class,
                () -> RunWorkspace.source(task.program(), "alias/main.cc"));
        assertThrows(IllegalArgumentException.class,
                () -> RunWorkspace.source(task.program(), "../main.cc"));
        assertThrows(IllegalArgumentException.class,
                () -> RunWorkspace.source(task.program(), "/tmp/main.cc"));
        var bytes = new ByteArrayOutputStream();
        try (var zip = new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry("alias/main.cc"));
            zip.write(65);
            zip.closeEntry();
        }
        assertThrows(java.io.IOException.class,
                () -> CasesRunHandler.extractZip(bytes.toByteArray(), task.program()));
        assertFalse(Files.exists(outside.resolve("main.cc")));
    }

    @Test
    public void readsRejectLinksDirectoriesAndExcessBytes() throws Exception {
        Path output = task.input("0.out", new byte[] {1, 2});
        assertArrayEquals(new byte[] {1, 2}, RunWorkspace.read(output, 2));
        assertThrows(java.io.IOException.class, () -> RunWorkspace.read(output, 1));
        Path alias = task.ioPath("link.out");
        Files.createSymbolicLink(alias, output);
        assertThrows(java.io.IOException.class, () -> RunWorkspace.read(alias, 2));
        assertThrows(java.io.IOException.class, () -> RunWorkspace.size(alias));
        assertThrows(java.io.IOException.class, () -> RunWorkspace.read(task.checker(), 2));
    }

    @Test
    public void writableOrLinkedParentsAreRejectedAndExistingTasksAreNotReused() throws Exception {
        assertThrows(java.nio.file.FileAlreadyExistsException.class,
                () -> RunWorkspace.create(parent, 42, 1));
        Path alias = Files.createSymbolicLink(temporary.resolve("alias"), parent);
        assertThrows(java.io.IOException.class, () -> RunWorkspace.create(alias, 43, 1));
        Files.setPosixFilePermissions(parent, PosixFilePermissions.fromString("rwxrwxrwx"));
        assertThrows(java.io.IOException.class, () -> RunWorkspace.create(parent, 43, 1));
    }

    @Test
    public void linuxWorkerPreservesProtectedFilesWhileProgramCanWriteItsOwnDirectory() throws Exception {
        Assume.assumeTrue("Linux root worker required",
                Integer.valueOf(0).equals(Files.getAttribute(parent, "unix:uid")));
        task.requireRootOwner();
        task.allowProgramWrites();
        Path input = task.input("0.in", "fixture".getBytes(StandardCharsets.UTF_8));
        var allowed = new ProcessBuilder("runuser", "-u", "nobody", "--", "sh", "-c",
                "printf ok > \"$1/probe\"", "fixture", task.program().toString()).start();
        assertTrue(allowed.waitFor(5, TimeUnit.SECONDS));
        assertEquals(0, allowed.exitValue());
        for (String command : new String[] {"printf changed > \"$1\"", "rm \"$1\""}) {
            var denied = new ProcessBuilder("runuser", "-u", "nobody", "--", "sh", "-c",
                    command, "fixture", input.toString()).start();
            assertTrue(denied.waitFor(5, TimeUnit.SECONDS));
            assertTrue(denied.exitValue() != 0);
        }
        assertEquals("fixture", Files.readString(input));
    }
}
