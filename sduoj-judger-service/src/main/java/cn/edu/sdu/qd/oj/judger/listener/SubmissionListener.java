package cn.edu.sdu.qd.oj.judger.listener;

import cn.edu.sdu.qd.oj.common.exception.InternalApiException;
import cn.edu.sdu.qd.oj.judger.client.JudgeTemplateClient;
import cn.edu.sdu.qd.oj.judger.client.SubmissionClient;
import cn.edu.sdu.qd.oj.judger.enums.JudgeStatus;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.handler.AbstractSubmissionHandler;
import cn.edu.sdu.qd.oj.judger.manager.SubmissionHandlerManager;
import cn.edu.sdu.qd.oj.judger.property.JudgerProperty;
import cn.edu.sdu.qd.oj.judger.sender.RabbitSender;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.CheckpointResultMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import com.rabbitmq.client.Channel;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.support.AmqpHeaders;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.concurrent.CompletionException;

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

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(value = "judge_queue", durable = "true"),
            exchange = @Exchange(value = "amq.direct", ignoreDeclarationExceptions = "true")),
            concurrency = "1"
    )
    public void pushSubmissionResult(SubmissionMessageDTO submissionMessageDTO, @Header(AmqpHeaders.DELIVERY_TAG) long deliveryTag, Channel channel) throws IOException, InternalApiException {
        log.info("submissionId {}, problemId {}, codeLength {}, judgeTemplateId {}", submissionMessageDTO.getSubmissionId(), submissionMessageDTO.getProblemId(), submissionMessageDTO.getCodeLength(), submissionMessageDTO.getJudgeTemplateId());

        SubmissionUpdateReqDTO updateReqDTO = null;
        try {
            // 查询评测模板
            JudgeTemplateDTO judgeTemplateDTO = judgeTemplateClient.query(submissionMessageDTO.getJudgeTemplateId());
            // 获取评测模板类型
            JudgeTemplateTypeEnum judgeTemplateTypeEnum = JudgeTemplateTypeEnum.of(judgeTemplateDTO.getType());
            // 取出具体的 handler
            AbstractSubmissionHandler handler = submissionHandlerManager.get(judgeTemplateTypeEnum);
            if (handler == null) {
                throw new SystemErrorException(String.format("Unexpected judge template type: %s", judgeTemplateDTO.getType()));
            }
            updateReqDTO = handler.handle(submissionMessageDTO, judgeTemplateDTO);
        } catch (CompletionException e) {
            updateReqDTO = SubmissionUpdateReqDTO.builder()
                    .submissionId(submissionMessageDTO.getSubmissionId())
                    .judgeResult(SubmissionJudgeResult.CE.code)
                    .judgeScore(0)
                    .usedTime(0)
                    .usedMemory(0)
                    .judgeLog(e.getMessage())
                    .build();
        } catch (SystemErrorException e) {
            updateReqDTO = SubmissionUpdateReqDTO.builder()
                    .submissionId(submissionMessageDTO.getSubmissionId())
                    .judgeResult(SubmissionJudgeResult.SE.code)
                    .judgeScore(0)
                    .usedTime(0)
                    .usedMemory(0)
                    .judgeLog(e.getMessage())
                    .build();
        } catch (Exception e) {
            e.printStackTrace();
            channel.basicNack(deliveryTag, false, true);
            // TODO: 解决死循环消费失败问题
        }
        // 更新 result 并 ack
        if (updateReqDTO != null) {
            for (int i = 0; i < 5; i++) {
                try {
                    // 更新 submission result
                    submissionClient.update(updateReqDTO);
                    // ack
                    channel.basicAck(deliveryTag, false);
                    // 发送 end 的 websocket
                    rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionMessageDTO.getSubmissionId(), JudgeStatus.END.code));
                    break;
                } catch (AmqpException e) {
                    log.warn("sendOneJudgeResult", e);
                    try {
                        Thread.sleep(i * 2000L);
                    } catch (Throwable ignore) {
                    }
                } catch (Exception e) {
                    log.error("sendOneJudgeResult", e);
                    break;
                }
            }
        }
    }
}