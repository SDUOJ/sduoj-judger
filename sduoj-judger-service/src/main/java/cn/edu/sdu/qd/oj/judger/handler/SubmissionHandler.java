package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.client.JudgeTemplateClient;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import org.springframework.beans.factory.annotation.Autowired;

import java.nio.file.Paths;

public abstract class SubmissionHandler {

    @Autowired
    protected JudgeTemplateClient judgeTemplateClient;

    protected SubmissionMessageDTO submissionMessageDTO;
    protected String workspaceDir;
    protected String userOutputDir;

    public abstract JudgeTemplateTypeEnum getSupportJudgeTemplateType();

    public abstract SubmissionUpdateReqDTO start(JudgeTemplateDTO judgeTemplateDTO) throws CompileErrorException, SystemErrorException;

    public void initializeWorkspace(SubmissionMessageDTO submissionMessageDTO) throws SystemErrorException {
        this.submissionMessageDTO = submissionMessageDTO;
        workspaceDir = Paths.get(PathConfig.WORKSPACE_DIR, String.valueOf(submissionMessageDTO.getSubmissionId())).toString();
        userOutputDir = Paths.get(workspaceDir, "output").toString();
        try {
            FileUtils.createDir(workspaceDir);
            FileUtils.createDir(userOutputDir);
            ProcessUtils.chown(workspaceDir, "nobody");
            ProcessUtils.chmod(workspaceDir, "711");
        } catch (Exception e) {
            throw new SystemErrorException("Can not initialize workspace:\n" + e.toString());
        }
    }
}
