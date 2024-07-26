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
import com.sduoj.common.util.collection.Lists;
import com.sduoj.common.util.collection.Pair;
import com.sduoj.submission.api.message.SubmissionWaitingMsgDTO;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class JudgerMqManager implements MqManager {

    public static final String SUBMISSION_QUEUE_NAME = "sduoj.judger.submission";

    @Override
    public List<Pair<String, String>> getRoutingQueueNamesAndRoutingKeys() {
        return Lists.newArrayList(
            new Pair<>(SUBMISSION_QUEUE_NAME, SubmissionWaitingMsgDTO.ROUTING_KEY)
        );
    }
}
