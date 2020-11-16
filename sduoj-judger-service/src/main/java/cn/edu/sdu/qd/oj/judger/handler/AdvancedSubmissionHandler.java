package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.config.PathConfig;
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
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import lombok.AllArgsConstructor;
import org.apache.commons.lang3.ArrayUtils;
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
        if (judgeTemplate.getZipFileId() != null) {
            ProcessUtils.unzip(Paths.get(PathConfig.ZIP_DIR, judgeTemplate.getZipFileId() + ".zip").toString(), workspaceDir);
        }

        // 用户文件或代码写入文件
        if (StringUtils.isNotBlank(submission.getCode())) {
            FileUtils.writeFile(userCodePath, submission.getCode());
        }
        if (submission.getZipFileId() != null) {
            ProcessUtils.unzip(Paths.get(PathConfig.ZIP_DIR, submission.getZipFileId() + ".zip").toString(), workspaceUserDir);
        }

        // 工作目录下的所有文件授权 717 给nobody读写权限
        ProcessUtils.chmod(workspaceDir + "/*", "717");
        // 执行 judgeTemplate 的脚本 ./jt.sh
        ProcessUtils.chmod(jtPath, "+x");

        String[] exeEnvs = System.getenv().entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue()).toArray(String[]::new);
        String[] exeArgs = ArrayUtils.toArray("-c", jtPath);
        Argument[] _args = ArrayUtils.toArray(
            new Argument(SandboxArgument.MAX_CPU_TIME, timeLimit),
            new Argument(SandboxArgument.MAX_REAL_TIME, timeLimit * 2),
            new Argument(SandboxArgument.MAX_MEMORY, memoryLimit * 1024L),
            new Argument(SandboxArgument.EXE_PATH, "/bin/sh"),
            new Argument(SandboxArgument.EXE_ARGS, exeArgs),
            new Argument(SandboxArgument.EXE_ENVS, exeEnvs),
            new Argument(SandboxArgument.OUTPUT_PATH, "jt.log"),
            new Argument(SandboxArgument.UID, 0),
            new Argument(SandboxArgument.GID, 0)
        );

        // 发送 judging 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionId, SubmissionJudgeResult.JUDGING.code));

        SandboxResultDTO sandboxResult = SandboxRunner.run(0, workspaceDir, _args);
        if (sandboxResult == null) {
            throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", jtPath));
        }

        String judgeLog = null;
        try {
            judgeLog = FileUtils.readFile(Paths.get(workspaceDir, "jt.log").toString());
        } catch(Exception ignored) {}

        // 若是 SE 可能
        SandboxResult sr = SandboxResult.of(sandboxResult.getResult());
        int judgeResult = sr.submissionJudgeResult.code;
        if (sr == SandboxResult.RUNTIME_ERROR) {
            judgeResult = ExitCode.getSubmissionResultCode(sandboxResult.getExitCode());
        }
        // 拼装结果
        return SubmissionUpdateReqDTO.builder()
                .submissionId(submissionId)
                .judgeResult(judgeResult)
                .judgeScore(SandboxResult.SUCCESS.equals(sandboxResult.getResult()) ? 100 : 0)
                .usedTime(sandboxResult.getCpuTime())
                .usedMemory(sandboxResult.getMemory())
                .judgeLog(judgeLog)
                .build();
    }

    @AllArgsConstructor
    private enum ExitCode {
        WA(111, SubmissionJudgeResult.WA),
        CE(112, SubmissionJudgeResult.CE);
        ;

        int code;
        SubmissionJudgeResult submissionJudgeResult;

        public static int getSubmissionResultCode(int exitCode) {
            for (ExitCode ec : ExitCode.values()) {
                if (ec.code == exitCode) {
                    return ec.submissionJudgeResult.code;
                }
            }
            return SubmissionJudgeResult.RE.code;
        }
    }
}
