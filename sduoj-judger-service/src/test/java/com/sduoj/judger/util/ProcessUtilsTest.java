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

import org.junit.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

public class ProcessUtilsTest {

    @Test
    public void completedCommandPreservesExitCodeAndStreams() {
        ProcessUtils.CommandResult result = ProcessUtils.execCmd(
                List.of("/bin/sh", "-c", "printf output; printf error >&2; exit 7"),
                null, null, 2, TimeUnit.SECONDS);
        assertEquals(7, result.exitCode);
        assertEquals("output", result.stdout);
        assertEquals("error", result.stderr);
    }

    @Test(timeout = 5000)
    public void deadlineStopsDescendantsBeforeReadingTheirStreams() throws Exception {
        Path pidFile = Files.createTempFile("sduoj-process-test-", ".pid");
        ProcessHandle child = null;
        try {
            ProcessUtils.CommandResult result = ProcessUtils.execCmd(
                    List.of("/bin/sh", "-c",
                            "sleep 15 & child=$!; printf '%s' \"$child\" > \"$1\"; wait \"$child\"",
                            "sduoj-process-test", pidFile.toString()),
                    null, null, 250, TimeUnit.MILLISECONDS);
            child = ProcessHandle.of(Long.parseLong(Files.readString(pidFile))).orElse(null);
            assertEquals(ProcessUtils.CommandResult.PROCESS_NOT_FINISHED, result.exitCode);
            long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
            while (child != null && child.isAlive() && System.nanoTime() < end) {
                Thread.sleep(10);
            }
            assertFalse(child != null && child.isAlive());
        } finally {
            if (child != null && child.isAlive()) {
                child.destroyForcibly();
            }
            Files.deleteIfExists(pidFile);
        }
    }
}
