/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.sender;

import cn.edu.sdu.qd.oj.common.mq.util.RabbitSenderUtils;
import cn.edu.sdu.qd.oj.submission.api.message.CheckpointResultMsgDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
* @Description 封装一层工具层，用于发送 mq 消息
**/
@Slf4j
@Component
public class RabbitSender {

    @Autowired
    private RabbitSenderUtils rabbitSenderUtils;

    /**
     * 发送单点评测结果
     */
    public void sendOneJudgeResult(CheckpointResultMsgDTO messageDTO) {
        rabbitSenderUtils.send(CheckpointResultMsgDTO.ROUTING_KEY, messageDTO);
    }
}
