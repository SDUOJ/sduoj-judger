package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.util.SpringContextUtils;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import com.google.common.collect.Maps;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.util.Map;

@Slf4j
@Component
public class SubmissionHandlerManager implements CommandLineRunner {

    private Map<JudgeTemplateTypeEnum, SubmissionHandler> handlers = Maps.newConcurrentMap();

    @Override
    public void run(String... args) throws Exception {
        try {
            Map<String, SubmissionHandler> handlerMap = SpringContextUtils.getApplicationContext().getBeansOfType(SubmissionHandler.class);
            for (SubmissionHandler handler : handlerMap.values()) {
                handlers.put(handler.getSupportJudgeTemplateType(), handler);
            }
        } catch (Throwable t) {
            log.error(t.getMessage(), t);
            System.exit(-1);
        }
        log.info("handler register {}", handlers);
    }

    public SubmissionHandler get(JudgeTemplateTypeEnum judgeTemplateTypeEnum) {
        if (judgeTemplateTypeEnum == null) {
            return null;
        }
        return handlers.get(judgeTemplateTypeEnum);
    }
}
