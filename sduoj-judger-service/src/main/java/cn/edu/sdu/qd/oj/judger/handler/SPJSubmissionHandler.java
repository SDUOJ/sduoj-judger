package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import org.springframework.stereotype.Component;

@Component
public class SPJSubmissionHandler extends AbstractSubmissionHandler {

    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.SPJ;
    }

    public SubmissionUpdateReqDTO start() throws CompileErrorException, SystemErrorException {
        return null;
    }
}
