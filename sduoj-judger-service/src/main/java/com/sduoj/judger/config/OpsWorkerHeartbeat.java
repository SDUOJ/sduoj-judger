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

import com.sduoj.common.rpc.client.OpsWorkerClient;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.UUID;

/** A random boot identifier avoids publishing host addresses to the metrics API. */
@Component
@EnableScheduling
@RequiredArgsConstructor
@Slf4j
public class OpsWorkerHeartbeat {
    private final OpsWorkerClient client;
    private final String workerId = UUID.randomUUID().toString();

    @Scheduled(fixedDelay = 10000)
    public void heartbeat() {
        try {
            client.heartbeat(workerId);
        } catch (Exception e) {
            log.debug("Worker heartbeat unavailable", e);
        }
    }
}
