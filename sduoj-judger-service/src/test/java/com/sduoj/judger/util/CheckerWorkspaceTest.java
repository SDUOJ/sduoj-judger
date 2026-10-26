package com.sduoj.judger.util;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SecureDirectoryStream;
import java.nio.file.attribute.PosixFilePermissions;
import org.junit.Before;
import org.junit.Assume;
import org.junit.Test;
import static org.junit.Assert.*;

public class CheckerWorkspaceTest {
    @Before
    public void requireSecureDirectoryProvider() throws Exception {
        // Production deletion deliberately has no path-based fallback. Run
        // these cleanup tests on the Linux provider that supplies this API.
        try (var entries = Files.newDirectoryStream(Path.of(System.getProperty("java.io.tmpdir")))) {
            Assume.assumeTrue("SecureDirectoryStream provider required",
                    entries instanceof SecureDirectoryStream<?>);
        }
    }

    @Test
    public void eachCaseGetsFreshCopiesAnAbsentWritableReportAndCleanup() throws Exception {
        Path task = Files.createTempDirectory("checker-case-test");
        try {
            Path artifacts = Files.createDirectory(task.resolve("checker"));
            Files.writeString(artifacts.resolve("checker"), "sealed executable");
            Path program = Files.createDirectory(task.resolve("program"));
            Path input = Files.writeString(task.resolve("input"), "1 2\n");
            Path output = Files.writeString(task.resolve("output"), "3\n");
            Path answer = Files.writeString(task.resolve("answer"), "3\n");
            Path first;
            try (var checker = CheckerWorkspace.create(task, artifacts, input, output, answer)) {
                first = checker.root();
                assertEquals("1 2\n", Files.readString(checker.input()));
                assertEquals("3\n", Files.readString(checker.answer()));
                assertFalse(Files.exists(checker.report()));
                assertFalse(Files.exists(program.resolve("case-answer")));
                assertEquals(PosixFilePermissions.fromString("r--r--r--"),
                        Files.getPosixFilePermissions(checker.answer()));
                Files.writeString(checker.report(), "this case only");
                assertTrue(checker.arguments().endsWith(" " + checker.report()));
            }
            assertFalse(Files.exists(first));
            try (var next = CheckerWorkspace.create(task, artifacts, input, output, answer)) {
                assertNotEquals(first, next.root());
                assertFalse(Files.exists(next.report()));
            }
            assertEquals("3\n", Files.readString(answer));
        } finally {
            WorkspaceFiles.delete(task);
        }
    }

    @Test
    public void checkerSourcesAndCaseInputsCannotIntroduceSymlinks() throws Exception {
        Path task = Files.createTempDirectory("checker-links");
        try {
            Path artifacts = Files.createDirectory(task.resolve("checker"));
            Path input = Files.writeString(task.resolve("input"), "x");
            Path output = Files.writeString(task.resolve("output"), "x");
            Path answer = Files.writeString(task.resolve("answer"), "x");
            Files.createSymbolicLink(artifacts.resolve("external"), input);
            assertThrows(java.io.IOException.class,
                    () -> CheckerWorkspace.create(task, artifacts, input, output, answer));
            Files.delete(artifacts.resolve("external"));
            Path link = Files.createSymbolicLink(task.resolve("answer-link"), answer);
            assertThrows(java.io.IOException.class,
                    () -> CheckerWorkspace.create(task, artifacts, input, output, link));
            try (var entries = Files.list(task)) {
                assertFalse(entries.anyMatch(p -> p.getFileName().toString().startsWith("checker-case-")));
            }
        } finally {
            WorkspaceFiles.delete(task);
        }
    }
}
