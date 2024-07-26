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

import com.sduoj.common.rpc.client.JudgeTemplateClient;
import com.sduoj.common.rpc.client.SubmissionClient;
import com.sduoj.judger.config.JudgerMqManager;
import com.sduoj.judger.exception.SystemErrorException;
import com.sduoj.judger.handler.AbstractSubmissionHandler;
import com.sduoj.judger.manager.SubmissionHandlerManager;
import com.sduoj.judger.property.JudgerProperty;
import com.sduoj.judger.sender.RabbitSender;
import com.sduoj.judgetemplate.dto.JudgeTemplateDTO;
import com.sduoj.judgetemplate.enums.JudgeTemplateTypeEnum;
import com.sduoj.submission.api.message.SubmissionWaitingMsgDTO;
import com.sduoj.submission.dto.SubmissionJudgeDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;


@Slf4j
@Component
@EnableConfigurationProperties(JudgerProperty.class)
public class SubmissionListener {

    @Autowired
    private SubmissionClient submissionClient;

    @Autowired
    private JudgeTemplateClient judgeTemplateClient;

    @Autowired
    private SubmissionHandlerManager submissionHandlerManager;

    @Autowired
    protected RabbitSender rabbitSender;

    @RabbitListener(queues = JudgerMqManager.SUBMISSION_QUEUE_NAME)
    public void handleSubmissionMessage(SubmissionWaitingMsgDTO messageDTO) throws Throwable {
        log.info("submissionId {}, version {}", messageDTO.getSubmissionId(), messageDTO.getVersion());
        try {
            // 查询提交
            SubmissionJudgeDTO submissionJudgeDTO = submissionClient.querySubmissionJudgeDTO(messageDTO.getSubmissionId(), messageDTO.getVersion());
            if (submissionJudgeDTO == null) {
                // 版本非最新，不需要评测
                return;
            }
            // 查询评测模板
            JudgeTemplateDTO judgeTemplateDTO = judgeTemplateClient.query(submissionJudgeDTO.getJudgeTemplateId());
            // 获取评测模板类型
            JudgeTemplateTypeEnum judgeTemplateTypeEnum = JudgeTemplateTypeEnum.of(judgeTemplateDTO.getType());
            // 取出具体的 handler
            AbstractSubmissionHandler handler = submissionHandlerManager.get(judgeTemplateTypeEnum);
            if (handler == null) {
                throw new SystemErrorException(String.format("Unexpected judge template type: %s", judgeTemplateDTO.getType()));
            }
            handler.handle(submissionJudgeDTO, judgeTemplateDTO);
        } catch (Throwable t) {
            log.error("", t);
            throw t;
        }
    }
}