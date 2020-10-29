package cn.edu.sdu.qd.oj.judger.sender;

import cn.edu.sdu.qd.oj.judger.dto.OneJudgeResult;
import com.alibaba.fastjson.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
* @Description 封装一层工具层，用于发送 mq 消息
**/
@Slf4j
@Component
public class RabbitSender {

    @Autowired
    private RabbitTemplate rabbitTemplate;

    /**
    * @Description 发送单点评测结果
    **/
    public void sendOneJudgeResult(OneJudgeResult oneJudgeResult) {
        for (int i = 0; i < 5; i++) {
            try {
                this.rabbitTemplate.convertAndSend(
                        "sduoj.submission.exchange",
                        "sduoj.submission.queue",
                        JSON.toJSONString(oneJudgeResult)
                );
                break;
            } catch (AmqpException e) {
                log.warn("sendOneJudgeResult", e);
            } catch (Exception e) {
                log.error("sendOneJudgeResult", e);
                break;
            }
        }
    }
}
