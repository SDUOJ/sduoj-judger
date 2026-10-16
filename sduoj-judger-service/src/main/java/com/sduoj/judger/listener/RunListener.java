/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.listener;

import com.sduoj.judger.client.RunClient;
import com.sduoj.judger.handler.CasesRunHandler;
import com.sduoj.submission.api.RunApi;
import com.sduoj.submission.api.message.SubmissionWaitingMsgDTO;
import com.sduoj.submission.dto.RunSpecDTO;

import lombok.RequiredArgsConstructor;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "sduoj.run.worker", havingValue = "true")
public class RunListener {
    private final RunClient client;
    private final CasesRunHandler handler;

    @RabbitListener(queues = RunApi.QUEUE)
    public void handle(SubmissionWaitingMsgDTO message) throws Exception {
        if (message.getBizType() == null
                || message.getBizType() < 100
                || message.getBizType() > 103) {
            throw new org.springframework.amqp.AmqpRejectAndDontRequeueException(
                    "Unsupported Run task type");
        }
        RunSpecDTO spec = client.claim(message.getSubmissionId(), message.getVersion());
        if (spec != null) handler.execute(spec);
    }
}
