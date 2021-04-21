/*
 * Copyright 2020-2021 the original author or authors.
 *
 * Licensed under the General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/gpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.common.util.CollectionUtils;
import cn.edu.sdu.qd.oj.judger.command.Command;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.dto.CommandExecuteResult;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.SandboxRunner;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateConfigDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submit.dto.CheckpointResultMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import com.alibaba.fastjson.JSON;
import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.ExecutionException;
import java.util.stream.Collectors;


/**
 * handle SPJ submission
 *
 * @author jeshrz
 * @author zhangt2333
 */
@Slf4j
@Component
public class SPJSubmissionHandler extends AbstractSubmissionHandler {

    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.SPJ;
    }

    protected SubmissionUpdateReqDTO start() throws CompileErrorException, SystemErrorException {
        // 如果检查点为空，直接报 SE
        if (CollectionUtils.isEmpty(checkpoints)) {
            throw new SystemErrorException("No checkpoint files!!");
        }

        // 评测基本信息
        long submissionId = submission.getSubmissionId();
        JudgeTemplateConfigDTO judgeTemplateConfigDTO = JSON.parseObject(judgeTemplate.getShellScript(), JudgeTemplateConfigDTO.class);
        // 编译选项
        JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig = judgeTemplateConfigDTO.getUser().getCompile();
        JudgeTemplateConfigDTO.TemplateConfig.Compile spjCompileConfig = judgeTemplateConfigDTO.getSpj().getCompile();
        // 运行选项
        JudgeTemplateConfigDTO.TemplateConfig.Run runConfig = judgeTemplateConfigDTO.getUser().getRun();
        JudgeTemplateConfigDTO.TemplateConfig.Run spjRunConfig = judgeTemplateConfigDTO.getSpj().getRun();

        // 格式串中获取题目数据
        compileConfig.setCommands(replacePatternToProblemInfo(compileConfig.getCommands()));
        spjCompileConfig.setCommands(replacePatternToProblemInfo(spjCompileConfig.getCommands()));
        runConfig.setCommand(replacePatternToProblemInfo(runConfig.getCommand()));
        spjRunConfig.setCommand(replacePatternToProblemInfo(spjRunConfig.getCommand()));

        // 题目配置：时间、空间、检查点分数
        int timeLimit = problem.getTimeLimit();
        int memoryLimit = problem.getMemoryLimit();

        SubmissionUpdateReqDTO result = SubmissionUpdateReqDTO.builder()
                .submissionId(submissionId)
                .judgeScore(0)
                .usedTime(0)
                .usedMemory(0)
                .build();

        // 发送 compiling 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionId, SubmissionJudgeResult.COMPILING.code));

        // 解压spj支持文件
        ProcessUtils.unzip(Paths.get(PathConfig.ZIP_DIR, judgeTemplate.getZipFileId() + ".zip").toString(), workspaceDir);
        // 用户代码写入文件
        String code = submission.getCode();
        FileUtils.writeFile(Paths.get(workspaceDir, compileConfig.getSrcName()).toString(), code);
        // 编译用户和spj代码
        compile(compileConfig, spjCompileConfig);

        // 发送 judging 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionId, SubmissionJudgeResult.JUDGING.code));

        // 提交评测任务到线程池
        for (int i = 0, checkpointNum = checkpoints.size(); i < checkpointNum; ++i) {
            String checkpointId = String.valueOf(checkpoints.get(i).getCheckpointId());
            String inputPath = Paths.get(PathConfig.DATA_DIR, checkpointId + ".in").toString();
            String answerPath = Paths.get(PathConfig.DATA_DIR, checkpointId + ".ans").toString();
            String outputPath = Paths.get(userOutputDir, checkpointId + ".out").toString();

            Integer checkpointScore = checkpoints.get(i).getCheckpointScore();

            commandExecutor.submit(new SPJJudgeCommand(submissionId, i, checkpointScore, timeLimit, memoryLimit, inputPath, outputPath, answerPath, runConfig, spjRunConfig));
        }

        // 收集评测结果
        int maxUsedTime = 0;
        int maxUsedMemory = 0;
        int judgeScore = 0;
        SubmissionJudgeResult judgeResult = SubmissionJudgeResult.AC;
        List<CheckpointResultMessageDTO> checkpointResults = new ArrayList<>();
        for (int i = 0, checkpointNum = checkpoints.size(); i < checkpointNum; ++i) {
            try {
                // 阻塞等待任一 checkpoint 测完
                CommandExecuteResult<CheckpointResultMessageDTO> executeResult = commandExecutor.take();

                // 取出结果发送一个 checkpoint 的结果
                CheckpointResultMessageDTO checkpointResultMessageDTO = executeResult.getResult();
                rabbitSender.sendOneJudgeResult(checkpointResultMessageDTO);
                checkpointResults.add(checkpointResultMessageDTO);

                maxUsedTime = Math.max(maxUsedTime, checkpointResultMessageDTO.getUsedTime());
                maxUsedMemory = Math.max(maxUsedMemory, checkpointResultMessageDTO.getUsedMemory());
                judgeScore += checkpointResultMessageDTO.getJudgeScore();

                if (SubmissionJudgeResult.AC.equals(judgeResult)) {
                    judgeResult = SubmissionJudgeResult.of(checkpointResultMessageDTO.getJudgeResult());
                }
            } catch (InterruptedException | ExecutionException e) {
                throw new SystemErrorException(e);
            }
        }

        // 组装最终评测结果
        checkpointResults.sort(Comparator.comparingInt(CheckpointResultMessageDTO::getCheckpointIndex));
        result.setCheckpointResults(checkpointResults.stream()
                .map(CheckpointResultMessageDTO::toEachCheckpointResult)
                .collect(Collectors.toList()));
        result.setJudgeResult(judgeResult.code);
        result.setJudgeScore(judgeScore);
        result.setUsedTime(maxUsedTime);
        result.setUsedMemory(maxUsedMemory);
        result.setJudgeLog(judgeLog);

        return result;
    }

    private void compile(JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig,
                         JudgeTemplateConfigDTO.TemplateConfig.Compile spjCompileConfig) throws CompileErrorException {
        try {
            String srcPath = compileConfig.getSrcName();
            String spjSrcPath = spjCompileConfig.getSrcName();

            log.info(String.format("Compiling \"%s\", spj: \"%s\"", srcPath, spjSrcPath));

            String compilerLogPath = "compiler.out";
            String[] exeEnvs = new String[1];
            exeEnvs[0] = "PATH=" + System.getenv("PATH");

            // 编译用户代码
            judgeLog = compileCode(compileConfig, exeEnvs, compilerLogPath);
            // 编译spj代码
            judgeLog += compileCode(spjCompileConfig, exeEnvs, compilerLogPath);

            log.info("Compiled");
        } catch (SystemErrorException e) {
            throw new CompileErrorException(e);
        }
    }

    private String compileCode(JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig,
                               String[] exeEnvs,
                               String compilerLogPath) throws SystemErrorException, CompileErrorException {
        StringBuilder sb = new StringBuilder();
        for (String eachCompileCommand : compileConfig.getCommands()) {
            String[] _commands = SPJSubmissionHandler.WHITESPACE_PATTERN.split(eachCompileCommand.trim());

            Argument _args = Argument.build()
                    .add(SandboxArgument.MAX_CPU_TIME, compileConfig.getMaxCpuTime())
                    .add(SandboxArgument.MAX_REAL_TIME, compileConfig.getMaxRealTime())
                    .add(SandboxArgument.MAX_MEMORY, compileConfig.getMaxMemory() * 1024L)
                    .add(SandboxArgument.MAX_STACK, 128 * 1024 * 1024L)
                    .add(SandboxArgument.MAX_OUTPUT_SIZE, 20 * 1024 * 1024) // 20MB
                    .add(SandboxArgument.EXE_PATH, _commands[0])
                    .add(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(_commands, 1, _commands.length))
                    .add(SandboxArgument.EXE_ENVS, exeEnvs)
                    .add(SandboxArgument.INPUT_PATH, "/dev/null")
                    .add(SandboxArgument.OUTPUT_PATH, compilerLogPath);

            SandboxResultDTO sandboxResultDTO = SandboxRunner.run(workspaceDir, _args);
            if (sandboxResultDTO == null) {
                throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", eachCompileCommand));
            }

            try {
                sb.append(FileUtils.readFile(Paths.get(workspaceDir, compilerLogPath).toString()));
            } catch (SystemErrorException e) {
                throw new CompileErrorException(sb.toString() + "\n" + e.toString());
            }

            if (!SandboxResult.SUCCESS.equals(sandboxResultDTO.getResult())) {
                throw new CompileErrorException(sb.toString());
            }
        }
        return sb.toString();
    }

    private class SPJJudgeCommand implements Command {
        private final long submissionId;
        private final int caseNo;
        private final int score;

        private final Argument runCommand;
        private final Argument spjRunCommand;

        SPJJudgeCommand(long submissionId, int caseNo, int score, int timeLimit, int memoryLimit, String inputPath,
                        String outputPath, String answerPath, JudgeTemplateConfigDTO.TemplateConfig.Run runConfig, JudgeTemplateConfigDTO.TemplateConfig.Run spjRunConfig) throws SystemErrorException {
            this.submissionId = submissionId;
            this.caseNo = caseNo;
            this.score = score;

            String[] _commands = SPJSubmissionHandler.WHITESPACE_PATTERN.split(runConfig.getCommand().trim());
            runCommand = Argument.build()
                    .add(SandboxArgument.MAX_CPU_TIME, timeLimit * runConfig.getMaxCpuTimeFactor())
                    .add(SandboxArgument.MAX_REAL_TIME, timeLimit * runConfig.getMaxRealTimeFactor())
                    .add(SandboxArgument.MAX_MEMORY, memoryLimit * runConfig.getMaxMemoryFactor() * 1024L)
                    .add(SandboxArgument.MAX_STACK, 128L * 1024 * 1024)
                    .add(SandboxArgument.EXE_PATH, _commands[0])
                    .add(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(_commands, 1, _commands.length))
                    .add(SandboxArgument.EXE_ENVS, runConfig.getEnvs())
                    .add(SandboxArgument.INPUT_PATH, inputPath)
                    .add(SandboxArgument.OUTPUT_PATH, outputPath)
                    .add(SandboxArgument.UID, PathConfig.NOBODY_UID)
                    .add(SandboxArgument.GID, PathConfig.NOBODY_GID);

            _commands = SPJSubmissionHandler.WHITESPACE_PATTERN.split(spjRunConfig.getCommand().trim());
            String exePath = _commands[0];
            // exeArgs 的格式为 <input-file> <output-file> <answer-file> <report-file> [<-appes>]
            String[] exeArgs = new String[4 + _commands.length - 1];
            exeArgs[0] = inputPath;
            exeArgs[1] = outputPath;
            exeArgs[2] = answerPath;
            exeArgs[3] = "spj.out";
            for (int i = 1, n = _commands.length; i < n; i++) {
                exeArgs[i + 3] = _commands[i];
            }

            spjRunCommand = Argument.build()
                    .add(SandboxArgument.MAX_CPU_TIME, timeLimit * spjRunConfig.getMaxCpuTimeFactor())
                    .add(SandboxArgument.MAX_REAL_TIME, timeLimit * spjRunConfig.getMaxRealTimeFactor())
                    .add(SandboxArgument.MAX_MEMORY, memoryLimit * spjRunConfig.getMaxMemoryFactor() * 1024L)
                    .add(SandboxArgument.MAX_STACK, 128L * 1024 * 1024)
                    .add(SandboxArgument.EXE_PATH, exePath)
                    .add(SandboxArgument.EXE_ARGS, exeArgs)
                    .add(SandboxArgument.EXE_ENVS, spjRunConfig.getEnvs())
                    .add(SandboxArgument.INPUT_PATH, "/dev/null")
                    .add(SandboxArgument.OUTPUT_PATH, "/dev/null")
                    .add(SandboxArgument.UID, PathConfig.NOBODY_UID)
                    .add(SandboxArgument.GID, PathConfig.NOBODY_GID);

        }

        @Override
        public CommandExecuteResult<CheckpointResultMessageDTO> run(int coreNo) {
            CommandExecuteResult<CheckpointResultMessageDTO> commandExecuteResult = null;
            try {
                SandboxResultDTO judgeResult = SandboxRunner.run(coreNo, workspaceDir, runCommand);
                if (SandboxResult.SYSTEM_ERROR.equals(judgeResult.getResult())) {
                    throw new SystemErrorException(String.format("Sandbox Internal Error #%d, signal #%d", judgeResult.getError(), judgeResult.getSignal()));
                } else if (SandboxResult.SUCCESS.equals(judgeResult.getResult())) {
                    SubmissionJudgeResult result = check(coreNo);
                    commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                            submissionId, caseNo, result.code,
                            SubmissionJudgeResult.AC.code == result.code ? score : 0, judgeResult.getCpuTime(), judgeResult.getMemory()
                    ));
                } else {
                    commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                            submissionId, caseNo, SandboxResult.of(judgeResult.getResult()).submissionJudgeResult.code,
                            0, judgeResult.getCpuTime(), judgeResult.getMemory()
                    ));
                }
            } catch (SystemErrorException e) {
                log.warn("", e);
                judgeLog += e + "\n";
                commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                        submissionId, caseNo, SubmissionJudgeResult.SE.code,
                        0, 0, 0
                ));
            } catch (Exception e) {
                log.warn("", e);
                throw e;
            }
            log.info("case {} finish", caseNo);
            return commandExecuteResult;
        }

        private SubmissionJudgeResult check(int coreNo) {
            try {
                SandboxResultDTO judgeResult = SandboxRunner.run(coreNo, workspaceDir, spjRunCommand);
                if (SandboxResult.SYSTEM_ERROR.equals(judgeResult.getResult())) {
                    throw new SystemErrorException(String.format("While special judging, Sandbox Internal Error #%d, signal #%d occurred", judgeResult.getError(), judgeResult.getSignal()));
                } else if (SandboxResult.SUCCESS.equals(judgeResult.getResult())) {
                    return SubmissionJudgeResult.AC;
                } else if (SandboxResult.RUNTIME_ERROR.equals(judgeResult.getResult())) {
                    return SPJSubmissionHandler.ExitCode.getSubmissionResultCode(judgeResult.getExitCode());
                }
            } catch (SystemErrorException e) {
                log.warn("", e);
            } catch (Exception e) {
                log.warn("", e);
                throw e;
            }
            return SubmissionJudgeResult.SE;
        }
    }

    @AllArgsConstructor
    private enum ExitCode {
        WA(1, SubmissionJudgeResult.WA),
        PE(2, SubmissionJudgeResult.PR),
        FAIL(3, SubmissionJudgeResult.WA),
        DIRT(4, SubmissionJudgeResult.WA),
        POINTS(7, SubmissionJudgeResult.WA),
        UNEXPECTED_EOF(8, SubmissionJudgeResult.WA),
        ;

        int code;
        SubmissionJudgeResult submissionJudgeResult;

        public static SubmissionJudgeResult getSubmissionResultCode(int exitCode) throws SystemErrorException {
            for (SPJSubmissionHandler.ExitCode ec : SPJSubmissionHandler.ExitCode.values()) {
                if (ec.code == exitCode) {
                    return ec.submissionJudgeResult;
                }
            }
            throw new SystemErrorException(String.format("Unexpected exit code %d in SPJ mode", exitCode));
        }
    }
}
