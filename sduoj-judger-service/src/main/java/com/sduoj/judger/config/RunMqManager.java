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

import com.sduoj.common.mq.MqManager;
import com.sduoj.common.util.collection.Pair;
import com.sduoj.submission.api.RunApi;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
@EnableFeignClients(basePackages = "com.sduoj.judger.client")
@ConditionalOnProperty(name = "sduoj.run.worker", havingValue = "true")
public class RunMqManager implements MqManager {
    @Override
    public List<Pair<String, String>> getRoutingQueueNamesAndRoutingKeys() {
        return List.of(new Pair<>(RunApi.QUEUE, RunApi.ROUTING_KEY));
    }
}
