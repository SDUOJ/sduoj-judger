package cn.edu.sdu.qd.oj.judger.listener;

import cn.edu.sdu.qd.oj.judger.client.JudgeTemplateClient;
import cn.edu.sdu.qd.oj.judger.client.SubmissionClient;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.handler.AbstractSubmissionHandler;
import cn.edu.sdu.qd.oj.judger.manager.SubmissionHandlerManager;
import cn.edu.sdu.qd.oj.judger.property.JudgerProperty;
import cn.edu.sdu.qd.oj.judger.sender.RabbitSender;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionJudgeDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionMessageDTO;
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

    @RabbitListener(queues = "judge_queue")
    public void handleSubmissionMessage(SubmissionMessageDTO messageDTO) throws Throwable {
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