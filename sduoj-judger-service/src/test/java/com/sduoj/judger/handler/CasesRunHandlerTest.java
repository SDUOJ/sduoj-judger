/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.handler;

import static org.junit.Assert.*;

import com.sduoj.problem.dto.ProblemCheckerConfigDTO;

import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class CasesRunHandlerTest {
    @Test
    public void allRunsUseTheConfiguredPredefinedCheckerIncludingTextCheckers() {
        for (String name : new String[] {"fcmp.cpp", "lcmp.cpp", "ncmp.cpp"}) {
            var checker = ProblemCheckerConfigDTO.builder().source(name).build();
            assertTrue(CasesRunHandler.usesPredefinedChecker(checker));
        }
        assertFalse(CasesRunHandler.usesPredefinedChecker(null));
        assertFalse(
                CasesRunHandler.usesPredefinedChecker(ProblemCheckerConfigDTO.builder().build()));
        assertFalse(
                CasesRunHandler.usesPredefinedChecker(
                        ProblemCheckerConfigDTO.builder()
                                .source("custom source")
                                .spj(
                                        new com.sduoj.judgetemplate.dto.JudgeTemplateConfigDTO
                                                .TemplateConfig())
                                .build()));
    }

    private static byte[] archive(String name, byte[] value) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry(name));
            zip.write(value);
            zip.closeEntry();
        }
        return bytes.toByteArray();
    }

    @Test
    public void zipRejectsTraversalAndExpansionAndDoesNotOverwriteExistingSource()
            throws Exception {
        Path directory = Files.createTempDirectory("run-zip");
        try {
            assertThrows(
                    IllegalArgumentException.class,
                    () ->
                            CasesRunHandler.extractZip(
                                    archive("../escape.cc", new byte[] {1}), directory));
            assertThrows(
                    IllegalArgumentException.class,
                    () ->
                            CasesRunHandler.extractZip(
                                    archive("/tmp/escape.cc", new byte[] {1}), directory));
            CasesRunHandler.extractZip(archive("main.cc", new byte[] {65}), directory);
            assertArrayEquals(new byte[] {65}, Files.readAllBytes(directory.resolve("main.cc")));
            assertThrows(
                    java.nio.file.FileAlreadyExistsException.class,
                    () ->
                            CasesRunHandler.extractZip(
                                    archive("main.cc", new byte[] {66}), directory));
            assertArrayEquals(new byte[] {65}, Files.readAllBytes(directory.resolve("main.cc")));
            assertThrows(
                    IllegalArgumentException.class,
                    () ->
                            CasesRunHandler.extractZip(
                                    archive("large.cc", new byte[16 * 1024 * 1024 + 1]),
                                    directory));
        } finally {
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(java.util.Comparator.reverseOrder()).toList()) {
                    Files.deleteIfExists(path);
                }
            }
        }
    }

    @Test
    public void prefixStaysInsideUtf8BudgetEvenForMalformedInput() throws Exception {
        Path file = Files.createTempFile("run-output", ".txt");
        try {
            Files.writeString(file, "中a");
            assertEquals("", CasesRunHandler.prefix(file, 2));
            assertEquals("中", CasesRunHandler.prefix(file, 3));
            Files.write(file, new byte[] {(byte) 0xff, (byte) 0xff, 65});
            String prefix = CasesRunHandler.prefix(file, 2);
            assertTrue(prefix.getBytes(StandardCharsets.UTF_8).length <= 2);
            assertEquals("", prefix);
        } finally {
            Files.deleteIfExists(file);
        }
    }

    @Test
    public void prefixRejectsAnOutputSymlink() throws Exception {
        Path directory = Files.createTempDirectory("run-links");
        Path file = directory.resolve("result");
        try {
            Files.createSymbolicLink(file, Path.of("/etc/passwd"));
            assertThrows(IllegalStateException.class, () -> CasesRunHandler.prefix(file, 100));
        } finally {
            Files.deleteIfExists(file);
            Files.deleteIfExists(directory);
        }
    }
}
