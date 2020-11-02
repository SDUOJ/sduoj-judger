package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.enums.JudgeStatus;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.SandboxRunner;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submit.dto.CheckpointResultMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Component;

import java.nio.file.Paths;

@Component
public class AdvancedSubmissionHandler extends AbstractSubmissionHandler {


    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.ADVANCED;
    }


    /**
    * @Description 进阶模式处理
    * 用户提交zip包被解压在 ./user 下
    * 用户提交代码为 ./user/user.code，需要脚本自行处理
    * 评测模板zip包被解压在 ./ 下
    * 评测模板脚本为 ./jt.sh
    **/
    protected SubmissionUpdateReqDTO start() throws SystemErrorException {
        // 题目配置：时间、空间、检查点分数
        long submissionId = submission.getSubmissionId();
        int timeLimit = problem.getTimeLimit();
        int memoryLimit = problem.getMemoryLimit();

        String workspaceUserDir = Paths.get(workspaceDir, "user").toString();
        String userCodePath = Paths.get(workspaceUserDir, "user.code").toString();
        String jtPath = Paths.get(workspaceDir, "jt.sh").toString();

        // shell 脚本代码写入文件
        FileUtils.writeFile(jtPath, judgeTemplate.getShellScript());

        // 用户文件或代码写入文件
        if (StringUtils.isNotBlank(submission.getCode())) {
            FileUtils.writeFile(userCodePath, submission.getCode());
        }
        if (submission.getZipFileId() != null) {
            ProcessUtils.unzip(Paths.get(PathConfig.ZIP_DIR, submission.getZipFileId() + ".zip").toString(), workspaceUserDir);
        }

        // 发送 judging 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionId, JudgeStatus.JUDGING.code));

        // 执行 judgeTemplate 的脚本 ./jt.sh
        ProcessUtils.chown(jtPath, "+x");
        Argument[] _args = new Argument[7];
        _args[0] = new Argument(SandboxArgument.MAX_CPU_TIME, timeLimit);
        _args[1] = new Argument(SandboxArgument.MAX_REAL_TIME, timeLimit);
        _args[2] = new Argument(SandboxArgument.MAX_MEMORY, memoryLimit * 1024L);
        _args[3] = new Argument(SandboxArgument.MAX_STACK, 128 * 1024 * 1024);
        _args[4] = new Argument(SandboxArgument.MAX_OUTPUT_SIZE, 1024 * 1024);
        _args[5] = new Argument(SandboxArgument.EXE_PATH, jtPath);

        SandboxResultDTO sandboxResult = SandboxRunner.run(0, workspaceDir, _args);
        if (sandboxResult == null) {
            throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", jtPath));
        }

        // 拼装结果
        return SubmissionUpdateReqDTO.builder()
                .submissionId(submissionId)
                .judgeResult(SandboxResult.of(sandboxResult.getResult()).submissionJudgeResult.code)
                .judgeScore(SandboxResult.SUCCESS.equals(sandboxResult.getResult()) ? 100 : 0)
                .usedTime(Math.max(sandboxResult.getCpuTime(), sandboxResult.getRealTime()))
                .usedMemory(sandboxResult.getMemory())
                .build();
    }
}
