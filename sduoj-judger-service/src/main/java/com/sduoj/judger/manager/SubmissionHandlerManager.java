/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.manager;

import com.alibaba.nacos.shaded.com.google.common.collect.Maps;
import com.sduoj.judger.handler.AbstractSubmissionHandler;
import com.sduoj.judger.util.SpringContextUtils;
import com.sduoj.judgetemplate.enums.JudgeTemplateTypeEnum;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.util.Map;

@Slf4j
@Component
public class SubmissionHandlerManager implements CommandLineRunner {

    private Map<JudgeTemplateTypeEnum, AbstractSubmissionHandler> handlers = Maps.newConcurrentMap();

    @Override
    public void run(String... args) throws Exception {
        try {
            Map<String, AbstractSubmissionHandler> handlerMap = SpringContextUtils.getApplicationContext().getBeansOfType(AbstractSubmissionHandler.class);
            for (AbstractSubmissionHandler handler : handlerMap.values()) {
                handlers.put(handler.getSupportJudgeTemplateType(), handler);
            }
        } catch (Throwable t) {
            log.error(t.getMessage(), t);
            System.exit(-1);
        }
        log.info("handler register {}", handlers);
    }

    public AbstractSubmissionHandler get(JudgeTemplateTypeEnum judgeTemplateTypeEnum) {
        if (judgeTemplateTypeEnum == null) {
            return null;
        }
        return handlers.get(judgeTemplateTypeEnum);
    }
}
