/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.handler;

import com.sduoj.judger.config.PathConfig;
import com.sduoj.judger.exception.CompileErrorException;
import com.sduoj.judger.exception.SystemErrorException;
import com.sduoj.judger.util.FileUtils;
import com.sduoj.judger.util.SandboxRunner;
import com.sduoj.judger.util.ShellUtils;
import com.sduoj.judgetemplate.enums.JudgeTemplateTypeEnum;
import com.sduoj.sandbox.dto.Argument;
import com.sduoj.sandbox.dto.SandboxResultDTO;
import com.sduoj.sandbox.enums.SandboxArgument;
import com.sduoj.sandbox.enums.SandboxResult;
import com.sduoj.submission.api.message.CheckpointResultMsgDTO;
import com.sduoj.submission.dto.SubmissionUpdateReqDTO;
import com.sduoj.submission.enums.SubmissionJudgeResult;
import lombok.AllArgsConstructor;
import org.apache.commons.lang3.ArrayUtils;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Component;

import java.nio.file.Paths;

/**
 * handle Advanced submission
 *
 * @author zhangt2333
 * @author jeshrz
 */
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
    protected SubmissionUpdateReqDTO start() throws SystemErrorException, CompileErrorException {
        // 题目配置：时间、空间、检查点分数
        long submissionId = submission.getSubmissionId();
        int timeLimit = problem.getTimeLimit();
        int memoryLimit = problem.getMemoryLimit();
        int outputLimit = problem.getOutputLimit();

        String workspaceUserDir = Paths.get(workspaceDir, "user").toString();
        String userCodePath = Paths.get(workspaceUserDir, "user.code").toString();
        String jtPath = Paths.get(workspaceDir, "jt.sh").toString();

        // shell 脚本代码写入文件
        FileUtils.writeFile(jtPath, judgeTemplate.getShellScript());
        if (judgeTemplate.getZipFileId() != null) {
            boolean isSucc = ShellUtils.unzip(Paths.get(PathConfig.ZIP_DIR,
                    judgeTemplate.getZipFileId() + ".zip").toString(), workspaceDir);
            if (!isSucc) {
                throw new SystemErrorException("Decompresses judge template failed");
            }
        }

        // 用户文件或代码写入文件
        if (StringUtils.isNotBlank(submission.getCode())) {
            FileUtils.writeFile(userCodePath, submission.getCode());
        }
        if (submission.getZipFileId() != null) {
            boolean isSucc = ShellUtils.unzip(Paths.get(PathConfig.ZIP_DIR,
                    submission.getZipFileId() + ".zip").toString(), workspaceUserDir);
            if (!isSucc) {
                throw new CompileErrorException("Decompresses user's zip file failed");
            }
        }

        // 工作目录下的所有文件授权给nobody读写权限
        ShellUtils.chmod(workspaceDir, "777");
        // 执行 judgeTemplate 的脚本 ./jt.sh
        ShellUtils.chmod(jtPath, "+x");

        String[] exeEnvs = System.getenv()
                                 .entrySet()
                                 .stream()
                                 .filter(entry -> entry.getKey().equals("LANG")
                                         || entry.getKey().equals("PATH")
                                         || entry.getKey().equals("TZ"))
                                 .map(entry -> entry.getKey() + "=" + entry.getValue())
                                 .toArray(String[]::new);

        String[] exeArgs = ArrayUtils.toArray("-c", jtPath);
        Argument _args = Argument.build()
                .add(SandboxArgument.MAX_CPU_TIME, timeLimit)
                .add(SandboxArgument.MAX_REAL_TIME, timeLimit * 2)
                .add(SandboxArgument.MAX_MEMORY, memoryLimit * 1024L)
                .add(SandboxArgument.MAX_OUTPUT_SIZE, outputLimit * 1024L)
                .add(SandboxArgument.EXE_PATH, "/bin/sh")
                .add(SandboxArgument.EXE_ARGS, exeArgs)
                .add(SandboxArgument.EXE_ENVS, exeEnvs)
                .add(SandboxArgument.OUTPUT_PATH, "jt.log")
                .add(SandboxArgument.UID, 0)
                .add(SandboxArgument.GID, 0);

        // 发送 judging 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMsgDTO(submissionId, submission.getVersion(),
                SubmissionJudgeResult.JUDGING.code));

        SandboxResultDTO sandboxResult = SandboxRunner.run(workspaceDir, _args);
        if (sandboxResult == null) {
            throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", jtPath));
        }

        String judgeLog = null;
        try {
            judgeLog = FileUtils.readFirstNChars(Paths.get(workspaceDir, "jt.log"), MAX_JUDGE_LOG);
        } catch(Exception ignored) {
        }

        // 若是 SE 可能
        SandboxResult sr = SandboxResult.of(sandboxResult.getResult());
        int judgeResult = sr.submissionJudgeResult.code;
        if (sr == SandboxResult.RUNTIME_ERROR) {
            judgeResult = ExitCode.getSubmissionResultCode(sandboxResult.getExitCode());
        }

        // 判断超时并配置超时时间
        int usedTime = sandboxResult.getCpuTime();
        if (SubmissionJudgeResult.TLE.equals(judgeResult)) {
            usedTime = Math.max(usedTime, sandboxResult.getRealTime());
        }

        // 读 jt.score
        int judgeScore = SandboxResult.SUCCESS.equals(sandboxResult.getResult()) ? 100 : 0;
        try {
            String judgeScoreStr = FileUtils.readFile(Paths.get(workspaceDir, "jt.score"));
            judgeScoreStr = judgeScoreStr.trim();
            if (judgeScoreStr.indexOf('.') != -1) {
                judgeScore = Math.max(judgeScore, (int) Double.parseDouble(judgeScoreStr));
            } else {
                judgeScore = Math.max(judgeScore, Integer.parseInt(judgeScoreStr));
            }
        } catch(Exception ignored) {
        }

        // 拼装结果
        return SubmissionUpdateReqDTO.builder()
                .submissionId(submissionId)
                .judgeResult(judgeResult)
                .judgeScore(judgeScore)
                .usedTime(usedTime)
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
