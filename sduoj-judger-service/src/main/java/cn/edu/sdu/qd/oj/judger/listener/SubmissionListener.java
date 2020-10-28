package cn.edu.sdu.qd.oj.judger.listener;

import cn.edu.sdu.qd.oj.judger.client.JudgeTemplateClient;
import cn.edu.sdu.qd.oj.judger.client.SubmissionClient;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.handler.SubmissionHandler;
import cn.edu.sdu.qd.oj.judger.handler.SubmissionHandlerManager;
import cn.edu.sdu.qd.oj.judger.property.JudgerProperty;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@EnableConfigurationProperties(JudgerProperty.class)
public class SubmissionListener {

    @Autowired
    private JudgerProperty judgerProperty;

    @Autowired
    private SubmissionClient submissionClient;

    @Autowired
    private JudgeTemplateClient judgeTemplateClient;

    @Autowired
    private SubmissionHandlerManager submissionHandlerManager;

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(value = "judge_queue", durable = "true"),
            exchange = @Exchange(value = "amq.direct", ignoreDeclarationExceptions = "true")
    )
    )
    public void pushSubmissionResult(SubmissionMessageDTO submissionMessageDTO) {
        log.info("rabbitMQ: {}", submissionMessageDTO);
        SubmissionUpdateReqDTO result = new SubmissionUpdateReqDTO();
        try {
            JudgeTemplateDTO judgeTemplateDTO = judgeTemplateClient.query(submissionMessageDTO.getSubmissionId());

            JudgeTemplateTypeEnum judgeTemplateTypeEnum = JudgeTemplateTypeEnum.of(judgeTemplateDTO.getType());
            SubmissionHandler handler = submissionHandlerManager.get(judgeTemplateTypeEnum);
            if (handler == null) {
                throw new SystemErrorException(String.format("Unexpected judge template type: %s", judgeTemplateDTO.getType()));
            }
            handler.initializeWorkspace(submissionMessageDTO);
            result = handler.start(judgeTemplateDTO);
        } catch (CompileErrorException e) {
            result.setJudgeResult(SubmissionJudgeResult.CE.code);
            result.setJudgeLog(e.toString());
        } catch (SystemErrorException e) {
            result.setJudgeResult(SubmissionJudgeResult.SE.code);
            result.setJudgeLog(e.toString());
        } finally {

        }
    }
}