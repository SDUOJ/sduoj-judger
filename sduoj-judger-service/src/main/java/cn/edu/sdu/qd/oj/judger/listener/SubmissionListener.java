package cn.edu.sdu.qd.oj.judger.listener;

import cn.edu.sdu.qd.oj.common.exception.InternalApiException;
import cn.edu.sdu.qd.oj.judger.client.JudgeTemplateClient;
import cn.edu.sdu.qd.oj.judger.client.SubmissionClient;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.handler.AbstractSubmissionHandler;
import cn.edu.sdu.qd.oj.judger.manager.SubmissionHandlerManager;
import cn.edu.sdu.qd.oj.judger.property.JudgerProperty;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionMessageDTO;
import com.rabbitmq.client.Channel;
import lombok.extern.slf4j.Slf4j;
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
            exchange = @Exchange(value = "amq.direct", ignoreDeclarationExceptions = "true")),
            concurrency = "1"
    )
    public void pushSubmissionResult(SubmissionMessageDTO submissionMessageDTO, @Header(AmqpHeaders.DELIVERY_TAG) long deliveryTag, Channel channel) throws IOException, InternalApiException {
        log.info("submissionId {}, problemId {}, codeLength {}, judgeTemplateId {}", submissionMessageDTO.getSubmissionId(), submissionMessageDTO.getProblemId(), submissionMessageDTO.getCodeLength(), submissionMessageDTO.getJudgeTemplateId());
        try {
            JudgeTemplateDTO judgeTemplateDTO = judgeTemplateClient.query(submissionMessageDTO.getJudgeTemplateId());

            JudgeTemplateTypeEnum judgeTemplateTypeEnum = JudgeTemplateTypeEnum.of(judgeTemplateDTO.getType());
            AbstractSubmissionHandler handler = submissionHandlerManager.get(judgeTemplateTypeEnum);
            if (handler == null) {
                throw new SystemErrorException(String.format("Unexpected judge template type: %s", judgeTemplateDTO.getType()));
            }

            submissionClient.update(handler.handle(submissionMessageDTO, judgeTemplateDTO));
            channel.basicAck(deliveryTag, false);
        } catch (Exception e) {
            e.printStackTrace();
            channel.basicNack(deliveryTag, false, true);
            // TODO: 解决死循环消费失败问题
        }

    }
}