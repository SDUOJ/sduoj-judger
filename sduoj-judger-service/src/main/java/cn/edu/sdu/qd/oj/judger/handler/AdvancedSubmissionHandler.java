package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import org.springframework.stereotype.Component;

@Component
public class AdvancedSubmissionHandler extends SubmissionHandler {


    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.ADVANCED;
    }


    @Override
    public SubmissionUpdateReqDTO start(JudgeTemplateDTO judgeTemplateDTO) throws CompileErrorException, SystemErrorException {
        return null;
    }
}
