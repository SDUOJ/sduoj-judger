/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.checkpoint.dto.CheckpointJudgerDTO;
import cn.edu.sdu.qd.oj.common.util.CollectionUtils;
import cn.edu.sdu.qd.oj.common.util.JsonUtils;
import cn.edu.sdu.qd.oj.judger.command.CommandResult;
import cn.edu.sdu.qd.oj.judger.command.CpuAffinityCommand;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judger.util.SandboxRunner;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateConfigDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.problem.dto.ProblemCheckerConfigDTO;
import cn.edu.sdu.qd.oj.problem.enums.ProblemCheckpointRelType;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submission.api.message.CheckpointResultMsgDTO;
import cn.edu.sdu.qd.oj.submission.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submission.enums.SubmissionJudgeResult;
import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.stream.Collectors;

/**
 * handle IO submission
 *
 * @author jeshrz
 * @author zhangt2333
 */
@Slf4j
@Component
public class IOSubmissionHandler extends AbstractSubmissionHandler {

    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.IO;
    }

    protected SubmissionUpdateReqDTO start() throws CompileErrorException, SystemErrorException {
        // 检查测试数据不为空
        if (CollectionUtils.isEmpty(checkpoints)) {
            throw new SystemErrorException("No checkpoint files in this problem, please contact the Administrator or TA");
        }
        // 检查 checkerConfig 不为空
        ProblemCheckerConfigDTO checkerConfigDTO = problem.getCheckerConfig();
        if (checkerConfigDTO == null) {
            throw new SystemErrorException("No checker config in this problem, please contact the Administrator or TA");
        }

        // 编译 checker
        JudgeTemplateConfigDTO.TemplateConfig.Run customCheckerRunConfig = null;
        if (localCheckerManager.isCheckerSourceFilenameExist(checkerConfigDTO.getSource())) {
            if (!localCheckerManager.isCheckerExist(checkerConfigDTO.getSource())) {
                localCheckerManager.compilePredefinedChecker(checkerConfigDTO.getSource());
            }
            checkerConfigDTO.setSource(checkerConfigDTO.getSource().substring(0, checkerConfigDTO.getSource().indexOf('.')));
            customCheckerRunConfig = JudgeTemplateConfigDTO.TemplateConfig.Run
                    .builder()
                    .command(Paths.get(PathConfig.CHECKER_DIR, checkerConfigDTO.getSource()).toString())
                    .maxCpuTimeFactor(2)
                    .maxRealTimeFactor(2)
                    .build();
        } else {
            // custom checker 代码写入文件并编译
            JudgeTemplateConfigDTO.TemplateConfig configDTO = checkerConfigDTO.getSpj();
            JudgeTemplateConfigDTO.TemplateConfig.Compile spjCompileConfig = configDTO.getCompile();
            customCheckerRunConfig = configDTO.getRun();
            customCheckerRunConfig.setCommand(replacePatternToProblemInfo(customCheckerRunConfig.getCommand()));
            FileUtils.writeFile(Paths.get(workspaceDir, spjCompileConfig.getSrcName()), checkerConfigDTO.getSource());
            compile(spjCompileConfig);
        }

        // 评测基本信息
        long submissionId = submission.getSubmissionId();
        JudgeTemplateConfigDTO judgeTemplateConfigDTO = JsonUtils.toObject(judgeTemplate.getShellScript(), JudgeTemplateConfigDTO.class);
        // 编译选项
        JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig = judgeTemplateConfigDTO.getUser().getCompile();
        // 运行选项
        JudgeTemplateConfigDTO.TemplateConfig.Run runConfig = judgeTemplateConfigDTO.getUser().getRun();
        // 格式串中获取题目数据
        compileConfig.setCommands(replacePatternToProblemInfo(compileConfig.getCommands()));
        runConfig.setCommand(replacePatternToProblemInfo(runConfig.getCommand()));

        // 发送 compiling 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMsgDTO(submissionId, submission.getVersion(),
                SubmissionJudgeResult.COMPILING.code));

        // 用户代码写入文件
        String code = submission.getCode();
        FileUtils.writeFile(Paths.get(workspaceDir, compileConfig.getSrcName()), code);
        // 编译
        compile(compileConfig);

        // 发送 judging 的 websocket
        rabbitSender.sendOneJudgeResult(new CheckpointResultMsgDTO(submissionId, submission.getVersion(),
                SubmissionJudgeResult.JUDGING.code));

        SubmissionUpdateReqDTO result = runCheckpoints(runConfig, customCheckerRunConfig,
                checkpoints, ProblemCheckpointRelType.TEST.code);

        // 测试全部的 public checkpoints
        SubmissionUpdateReqDTO publicResult = runCheckpoints(runConfig, customCheckerRunConfig,
                publicCheckpoints, ProblemCheckpointRelType.PUBLIC.code);
        result.setPublicCheckpointNum(publicResult.getCheckpointNum());
        result.setPublicCheckpointResults(publicResult.getCheckpointResults());

        return result;
    }

    private SubmissionUpdateReqDTO runCheckpoints(JudgeTemplateConfigDTO.TemplateConfig.Run runConfig,
                                                  JudgeTemplateConfigDTO.TemplateConfig.Run customCheckerRunConfig,
                                                  List<CheckpointJudgerDTO> checkpointsToRun,
                                                  int checkpointType) throws SystemErrorException {
        // 题目配置：时间、空间、检查点分数
        long submissionId = submission.getSubmissionId();
        int timeLimit = problem.getTimeLimit();
        int memoryLimit = problem.getMemoryLimit();
        int outputLimit = problem.getOutputLimit();

        SubmissionUpdateReqDTO result = SubmissionUpdateReqDTO
                .builder()
                .submissionId(submissionId)
                .judgeScore(0)
                .usedTime(0)
                .usedMemory(0)
                .build();

        // 提交评测任务到线程池
        for (int i = 0, checkpointNum = checkpointsToRun.size(); i < checkpointNum; ++i) {
            long checkpointId = checkpointsToRun.get(i).getCheckpointId();
            String checkpointIdStr = String.valueOf(checkpointId);
            String inputPath = Paths.get(PathConfig.DATA_DIR, checkpointIdStr + ".in").toString();
            String answerPath = Paths.get(PathConfig.DATA_DIR, checkpointIdStr + ".ans").toString();
            String outputPath = Paths.get(userOutputDir, checkpointIdStr + ".out").toString();

            Integer checkpointScore = checkpointsToRun.get(i).getCheckpointScore();

            cpuAffinityThreadPool.submit(new IOJudgeCpuAffinityCommand(
                    submissionId, i,
                    checkpointId, checkpointType, checkpointScore,
                    timeLimit, memoryLimit, outputLimit,
                    inputPath, outputPath, answerPath,
                    runConfig, customCheckerRunConfig
            ));
        }

        // 收集评测结果
        int maxUsedTime = 0;
        int maxUsedMemory = 0;
        int judgeScore = 0;
        SubmissionJudgeResult judgeResult = SubmissionJudgeResult.AC;
        List<CheckpointResultMsgDTO> checkpointResults = new ArrayList<>();
        for (int i = 0, checkpointNum = checkpointsToRun.size(); i < checkpointNum; ++i) {
            try {
                // 阻塞等待任一 checkpoint 测完
                CommandResult<CheckpointResultMsgDTO> executeResult = cpuAffinityThreadPool.take();

                // 取出结果发送一个 checkpoint 的结果
                CheckpointResultMsgDTO checkpointResultMessageDTO = executeResult.getResult();
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
        checkpointResults.sort(Comparator.comparingInt(CheckpointResultMsgDTO::getCheckpointIndex));
        result.setCheckpointResults(checkpointResults
                .stream()
                .map(CheckpointResultMsgDTO::toEachCheckpointResult)
                .collect(Collectors.toList()));
        result.setCheckpointNum(result.getCheckpointResults().size());
        result.setJudgeResult(judgeResult.code);
        result.setJudgeScore(judgeScore);
        result.setUsedTime(maxUsedTime);
        result.setUsedMemory(maxUsedMemory);
        result.setJudgeLog(judgeLog);

        return result;
    }

    private void compile(JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig) throws CompileErrorException {
        try {
            String srcPath = compileConfig.getSrcName();

            log.info(String.format("Compiling \"%s\"", srcPath));

            String compilerLogPath = "compiler.out";
            String[] exeEnvs = new String[1];
            exeEnvs[0] = "PATH=" + System.getenv("PATH");

            StringBuilder sb = new StringBuilder();

            for (String eachCompileCommand : compileConfig.getCommands()) {
                String[] _commands = IOSubmissionHandler.WHITESPACE_PATTERN.split(eachCompileCommand.trim());

                Argument _args = Argument.build()
                        .add(SandboxArgument.MAX_CPU_TIME, compileConfig.getMaxCpuTime())
                        .add(SandboxArgument.MAX_REAL_TIME, compileConfig.getMaxRealTime())
                        .add(SandboxArgument.MAX_MEMORY, compileConfig.getMaxMemory() * 1024L)
                        .add(SandboxArgument.MAX_STACK, 128 * 1024 * 1024L)
                        .add(SandboxArgument.MAX_OUTPUT_SIZE, 20 * 1024 * 1024L) // 20MB
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
                    sb.append(FileUtils.readFile(Paths.get(workspaceDir, compilerLogPath)));
                } catch (SystemErrorException e) {
                    throw new CompileErrorException(sb.toString());
                }

                if (!SandboxResult.SUCCESS.equals(sandboxResultDTO.getResult())) {
                    throw new CompileErrorException(sb.toString());
                }
            }
            log.info("Compiled");
            judgeLog = sb.toString();
        } catch (SystemErrorException e) {
            throw new CompileErrorException(e);
        }
    }

    private class IOJudgeCpuAffinityCommand implements CpuAffinityCommand {

        private final long submissionId;
        private final int caseNo;
        private final long checkpointId;
        private final int checkpointType;
        private final int score;
        private final String outputPath;
        private final String answerPath;

        private final Argument runCommand;
        private final Argument customCheckerRunCommand;

        IOJudgeCpuAffinityCommand(long submissionId, int caseNo, long checkpointId, int checkpointType,
                                  int score, int timeLimit, int memoryLimit, int outputLimit,
                                  String inputPath, String outputPath, String answerPath,
                                  JudgeTemplateConfigDTO.TemplateConfig.Run runConfig,
                                  JudgeTemplateConfigDTO.TemplateConfig.Run customCheckerConfig) throws SystemErrorException {
            this.submissionId = submissionId;
            this.caseNo = caseNo;
            this.checkpointId = checkpointId;
            this.checkpointType = checkpointType;
            this.score = score;
            this.outputPath = outputPath;
            this.answerPath = answerPath;

            String[] commands = WHITESPACE_PATTERN.split(runConfig.getCommand().trim());

            runCommand = Argument.build()
                    .add(SandboxArgument.MAX_CPU_TIME, timeLimit * runConfig.getMaxCpuTimeFactor())
                    .add(SandboxArgument.MAX_REAL_TIME, timeLimit * runConfig.getMaxRealTimeFactor())
                    .add(SandboxArgument.MAX_MEMORY, memoryLimit * runConfig.getMaxMemoryFactor() * 1024L)
                    .add(SandboxArgument.MAX_OUTPUT_SIZE, outputLimit * 1024L)
                    .add(SandboxArgument.MAX_STACK, 128L * 1024 * 1024)
                    .add(SandboxArgument.EXE_PATH, commands[0])
                    .add(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(commands, 1, commands.length))
                    .add(SandboxArgument.EXE_ENVS, runConfig.getEnvs())
                    .add(SandboxArgument.INPUT_PATH, inputPath)
                    .add(SandboxArgument.OUTPUT_PATH, outputPath)
                    .add(SandboxArgument.SECCOMP_RULES, runConfig.getSeccompRule())
                    .add(SandboxArgument.UID, PathConfig.NOBODY_UID)
                    .add(SandboxArgument.GID, PathConfig.NOBODY_GID);


            commands = WHITESPACE_PATTERN.split(customCheckerConfig.getCommand().trim());
            // exeArgs 的格式为 <input-file> <output-file> <answer-file> <report-file> [<-appes>]
            String[] exeArgs = new String[4 + commands.length - 1];
            exeArgs[0] = inputPath;
            exeArgs[1] = outputPath;
            exeArgs[2] = answerPath;
            exeArgs[3] = "checker.out";
            for (int i = 1, n = commands.length; i < n; i++) {
                exeArgs[i + 3] = commands[i];
            }

            customCheckerRunCommand = Argument.build()
                    .add(SandboxArgument.MAX_CPU_TIME, timeLimit * customCheckerConfig.getMaxCpuTimeFactor())
                    .add(SandboxArgument.MAX_REAL_TIME, timeLimit * customCheckerConfig.getMaxRealTimeFactor())
                    .add(SandboxArgument.MAX_MEMORY, Math.max(64 * 1024 * 1024L, memoryLimit * customCheckerConfig.getMaxMemoryFactor() * 1024L))
                    .add(SandboxArgument.MAX_OUTPUT_SIZE, outputLimit * 1 * 1024L)
                    .add(SandboxArgument.MAX_STACK, 128L * 1024 * 1024)
                    .add(SandboxArgument.EXE_PATH, commands[0])
                    .add(SandboxArgument.EXE_ARGS, exeArgs)
                    .add(SandboxArgument.EXE_ENVS, customCheckerConfig.getEnvs())
                    .add(SandboxArgument.INPUT_PATH, "/dev/null")
                    .add(SandboxArgument.OUTPUT_PATH, "/dev/null")
                    .add(SandboxArgument.SECCOMP_RULES, customCheckerConfig.getSeccompRule())
                    .add(SandboxArgument.UID, PathConfig.NOBODY_UID)
                    .add(SandboxArgument.GID, PathConfig.NOBODY_GID);
        }

        @Override
        public CommandResult<CheckpointResultMsgDTO> run(int coreNo) {
            CommandResult<CheckpointResultMsgDTO> commandResult = null;
            try {
                SandboxResultDTO judgeResult = SandboxRunner.run(coreNo, workspaceDir, runCommand);
                if (SandboxResult.SYSTEM_ERROR.equals(judgeResult.getResult())) {
                    throw new SystemErrorException(String.format("Sandbox Internal Error #%d, signal #%d", judgeResult.getError(), judgeResult.getSignal()));
                } else if (SandboxResult.SUCCESS.equals(judgeResult.getResult())) {
                    SubmissionJudgeResult result = check(coreNo);
                    commandResult = new CommandResult<>(new CheckpointResultMsgDTO(
                            submissionId, submission.getVersion(),
                            checkpointType, caseNo, checkpointId,
                            result.code, SubmissionJudgeResult.AC.code == result.code ? score : 0,
                            judgeResult.getCpuTime(), judgeResult.getMemory()
                    ));
                } else {
                    int time = judgeResult.getCpuTime();
                    if (SandboxResult.CPU_TIME_LIMIT_EXCEEDED.equals(judgeResult.getResult())
                            || SandboxResult.REAL_TIME_LIMIT_EXCEEDED.equals(judgeResult.getResult())) {
                        time = Math.max(judgeResult.getCpuTime(), judgeResult.getRealTime());
                    }

                    commandResult = new CommandResult<>(new CheckpointResultMsgDTO(
                            submissionId, submission.getVersion(),
                            checkpointType, caseNo, checkpointId,
                            SandboxResult.of(judgeResult.getResult()).submissionJudgeResult.code, 0,
                            time, judgeResult.getMemory()
                    ));
                }
            } catch (SystemErrorException e) {
                log.warn("", e);
                judgeLog += e + "\n";
                commandResult = new CommandResult<>(new CheckpointResultMsgDTO(
                        submissionId, submission.getVersion(),
                        checkpointType, caseNo, checkpointId,
                        SubmissionJudgeResult.SE.code, 0,
                        0, 0
                ));
            } catch (Exception e) {
                log.warn("", e);
                throw e;
            }
            log.info("case {} finish", caseNo);
            return commandResult;
        }

        private SubmissionJudgeResult check(int coreNo) {
            try {
                SandboxResultDTO judgeResult = SandboxRunner.run(coreNo, workspaceDir, customCheckerRunCommand);
                if (SandboxResult.SYSTEM_ERROR.equals(judgeResult.getResult())) {
                    throw new SystemErrorException(String.format("While special judging, Sandbox Internal Error #%d, signal #%d occurred", judgeResult.getError(), judgeResult.getSignal()));
                } else if (SandboxResult.SUCCESS.equals(judgeResult.getResult())) {
                    return SubmissionJudgeResult.AC;
                } else if (SandboxResult.RUNTIME_ERROR.equals(judgeResult.getResult())) {
                    return ExitCode.getSubmissionResultCode(judgeResult.getExitCode());
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
            for (ExitCode ec : ExitCode.values()) {
                if (ec.code == exitCode) {
                    return ec.submissionJudgeResult;
                }
            }
            throw new SystemErrorException(String.format("Unexpected exit code %d in SPJ mode", exitCode));
        }
    }
}
