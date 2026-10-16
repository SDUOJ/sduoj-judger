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

import com.sduoj.judger.client.RunClient;
import com.sduoj.judger.util.WorkspaceFiles;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Instant;
import java.util.regex.Pattern;

/** Reap crash leftovers only after the local execution budget and server lease have elapsed. */
@Component
@ConditionalOnProperty(name = "sduoj.run.worker", havingValue = "true")
@RequiredArgsConstructor
@Slf4j
public class RunWorkspaceRetention {
    private static final Pattern NAME = Pattern.compile("run-([1-9][0-9]{0,18})-([1-9][0-9]{0,9})");
    private final RunClient client;

    @Value("${sduoj.run.workspace-retention.enabled:true}")
    private boolean enabled;

    @Value("${sduoj.run.workspace-retention.grace-seconds:300}")
    private int graceSeconds;

    @Scheduled(
            initialDelayString = "${sduoj.run.workspace-retention.initial-delay-ms:10000}",
            fixedDelayString = "${sduoj.run.workspace-retention.interval-ms:60000}")
    public void scheduled() {
        if (!enabled) {
            return;
        }
        try {
            int removed = clean(Path.of(PathConfig.WORKSPACE_DIR), Instant.now(), graceSeconds);
            if (removed > 0) {
                log.info("Removed {} expired Run workspaces", removed);
            }
        } catch (Exception e) {
            log.warn("Run workspace retention failed; remaining workspaces retained", e);
        }
    }

    int clean(Path root, Instant now, int grace) throws IOException {
        // Execution is bounded to 95 seconds plus its last stage; the server lease is 120 seconds.
        if (grace < 180 || grace > 86400) {
            throw new IllegalArgumentException("Workspace grace must be in 180..86400 seconds");
        }
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) {
            return 0;
        }
        int scanned = 0;
        int removed = 0;
        try (var entries = Files.newDirectoryStream(root, "run-*")) {
            for (Path entry : entries) {
                if (++scanned > 1000 || removed == 100) {
                    break;
                }
                var match = NAME.matcher(entry.getFileName().toString());
                if (!match.matches()) {
                    continue;
                }
                try {
                    long id = Long.parseLong(match.group(1));
                    int version = Integer.parseInt(match.group(2));
                    var attributes =
                            Files.readAttributes(
                                    entry, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                    if (!attributes.isDirectory()
                            || !attributes
                                    .lastModifiedTime()
                                    .toInstant()
                                    .isBefore(now.minusSeconds(grace))) {
                        continue;
                    }
                    // RPC exceptions are not evidence of expiry. Never delete on a failed lookup.
                    if (!client.active(id, version)) {
                        WorkspaceFiles.delete(entry);
                        removed++;
                    }
                } catch (Exception e) {
                    log.debug("Run workspace retained: {}", entry.getFileName(), e);
                }
            }
        }
        return removed;
    }
}
