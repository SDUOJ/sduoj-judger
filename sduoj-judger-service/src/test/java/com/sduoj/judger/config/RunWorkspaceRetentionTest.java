/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;
import static org.junit.Assume.assumeTrue;

import com.sduoj.judger.client.RunClient;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SecureDirectoryStream;
import java.nio.file.attribute.FileTime;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.function.BiPredicate;

public class RunWorkspaceRetentionTest {
    private Path temporary;
    private Path root;
    private final Instant now = Instant.now();
    private final List<String> checked = new ArrayList<>();

    @Before
    public void setup() throws Exception {
        temporary = Files.createTempDirectory("workspace-retention-");
        root = Files.createDirectory(temporary.resolve("workspace"));
    }

    @After
    public void cleanup() throws Exception {
        // Fixture files are trusted; macOS's provider does not offer SecureDirectoryStream.
        try (var paths = Files.walk(temporary)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                Files.deleteIfExists(path);
            }
        }
    }

    private boolean secureProvider() throws Exception {
        try (var entries = Files.newDirectoryStream(root)) {
            return entries instanceof SecureDirectoryStream<?>;
        }
    }

    private RunWorkspaceRetention cleaner(BiPredicate<Long, Integer> active) {
        RunClient client =
                (RunClient)
                        Proxy.newProxyInstance(
                                RunClient.class.getClassLoader(),
                                new Class<?>[] {RunClient.class},
                                (proxy, method, args) -> {
                                    if (!"active".equals(method.getName())) {
                                        throw new AssertionError("Unexpected RPC: " + method);
                                    }
                                    checked.add(args[0] + ":" + args[1]);
                                    return active.test((Long) args[0], (Integer) args[1]);
                                });
        return new RunWorkspaceRetention(client);
    }

    private Path workspace(String name, int age) throws Exception {
        Path path = Files.createDirectory(root.resolve(name));
        Files.writeString(path.resolve("source.cc"), "program");
        Files.setLastModifiedTime(path, FileTime.from(now.minusSeconds(age)));
        return path;
    }

    @Test
    public void expiredInactiveWorkspaceIsRemovedWithoutFollowingProgramLinks() throws Exception {
        assumeTrue("Linux worker provider required", secureProvider());
        Path outside = Files.createDirectory(temporary.resolve("shared-files"));
        Path sentinel = Files.writeString(outside.resolve("keep"), "shared");
        Path abandoned = workspace("run-123-1", 600);
        Path nested = Files.createDirectory(abandoned.resolve("nested"));
        Files.createSymbolicLink(nested.resolve("external"), outside);
        Files.createSymbolicLink(abandoned.resolve("dangling"), temporary.resolve("missing"));
        Files.setLastModifiedTime(abandoned, FileTime.from(now.minusSeconds(600)));

        assertEquals(1, cleaner((id, version) -> false).clean(root, now, 300));
        assertFalse(Files.exists(abandoned, LinkOption.NOFOLLOW_LINKS));
        assertEquals("shared", Files.readString(sentinel));
        assertEquals(List.of("123:1"), checked);
    }

    @Test
    public void activeAndRecentWorkspacesSurvive() throws Exception {
        Path active = workspace("run-124-2", 600);
        Path recent = workspace("run-125-1", 100);
        assertEquals(0, cleaner((id, version) -> true).clean(root, now, 300));
        assertTrue(Files.exists(active));
        assertTrue(Files.exists(recent));
        assertEquals(List.of("124:2"), checked);
    }

    @Test
    public void RpcFailureRetainsWorkspace() throws Exception {
        Path abandoned = workspace("run-126-1", 600);
        assertEquals(
                0,
                cleaner(
                                (id, version) -> {
                                    throw new IllegalStateException("problem-service unavailable");
                                })
                        .clean(root, now, 300));
        assertTrue(Files.exists(abandoned.resolve("source.cc")));
    }

    @Test
    public void formalUnknownInvalidAndSymlinkNamesAreNeverCandidates() throws Exception {
        for (String name :
                List.of(
                        "127",
                        "run-0-1",
                        "run-128-0",
                        "run-9223372036854775808-1",
                        "run-129-2147483648",
                        "run-other-1")) {
            workspace(name, 600);
        }
        Path outside = Files.createDirectory(temporary.resolve("outside"));
        Files.createSymbolicLink(root.resolve("run-130-1"), outside);
        Files.writeString(root.resolve("run-131-1"), "not a directory");
        assertEquals(0, cleaner((id, version) -> false).clean(root, now, 300));
        assertTrue(checked.isEmpty());
        try (var entries = Files.list(root)) {
            assertEquals(8, entries.count());
        }
    }

    @Test
    public void batchesAreBoundedAndNextPassCompletesTheRemainder() throws Exception {
        assumeTrue("Linux worker provider required", secureProvider());
        for (int id = 1000; id < 1101; id++) {
            workspace("run-" + id + "-1", 600);
        }
        RunWorkspaceRetention cleaner = cleaner((id, version) -> false);
        assertEquals(100, cleaner.clean(root, now, 300));
        assertEquals(1, cleaner.clean(root, now, 300));
        assertEquals(0, cleaner.clean(root, now, 300));
        assertEquals(101, checked.size());
    }

    @Test
    public void unsafeGraceAndSymlinkRootFailClosed() throws Exception {
        Path abandoned = workspace("run-132-1", 600);
        RunWorkspaceRetention cleaner = cleaner((id, version) -> false);
        assertThrows(IllegalArgumentException.class, () -> cleaner.clean(root, now, 179));
        assertThrows(IllegalArgumentException.class, () -> cleaner.clean(root, now, 86401));
        Path alias = Files.createSymbolicLink(temporary.resolve("root-alias"), root);
        assertEquals(0, cleaner.clean(alias, now, 300));
        assertTrue(Files.exists(abandoned));
        assertTrue(checked.isEmpty());
    }

    @Test
    public void insecureProviderDoesNotFallBackToPathBasedDeletion() throws Exception {
        assumeTrue("Unsupported provider required", !secureProvider());
        Path abandoned = workspace("run-133-1", 600);
        assertEquals(0, cleaner((id, version) -> false).clean(root, now, 300));
        assertTrue(Files.exists(abandoned.resolve("source.cc")));
    }
}
