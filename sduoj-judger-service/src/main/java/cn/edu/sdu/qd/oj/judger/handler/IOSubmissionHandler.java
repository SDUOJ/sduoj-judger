package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.command.Command;
import cn.edu.sdu.qd.oj.judger.command.CommandExecutor;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.dto.CommandExecuteResult;
import cn.edu.sdu.qd.oj.submit.dto.CheckpointResultMessageDTO;
import cn.edu.sdu.qd.oj.judger.enums.JudgeStatus;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.sender.RabbitSender;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateConfigDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.judger.util.SandboxRunner;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submit.dto.EachCheckpointResult;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import com.alibaba.fastjson.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.ExecutionException;
import java.util.stream.Collectors;


@Slf4j
@Component
public class IOSubmissionHandler extends AbstractSubmissionHandler {

    private String judgeLog;

    @Autowired
    private CommandExecutor commandExecutor;


    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.IO;
    }

    protected SubmissionUpdateReqDTO start() throws CompileErrorException, SystemErrorException {
        // 评测基本信息
        long submissionId = submission.getSubmissionId();
        JudgeTemplateConfigDTO judgeTemplateConfigDTO = JSON.parseObject(judgeTemplate.getShellScript(), JudgeTemplateConfigDTO.class);
        // 编译选项
        JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig = judgeTemplateConfigDTO.getUser().getCompile();
        // 运行选项
        JudgeTemplateConfigDTO.TemplateConfig.Run runConfig = judgeTemplateConfigDTO.getUser().getRun();

        // 题目配置：时间、空间、检查点分数
        int timeLimit = problem.getTimeLimit();
        int memoryLimit = problem.getMemoryLimit();

        SubmissionUpdateReqDTO result = SubmissionUpdateReqDTO.builder()
                .submissionId(submissionId)
                .judgeScore(0)
                .usedTime(0)
                .usedMemory(0)
                .build();

        try {
            // 发送 compiling 的 websocket
            rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionId, JudgeStatus.COMPILING.code));

            // 编译
            compile(compileConfig);

            // 发送 judging 的 websocket
            rabbitSender.sendOneJudgeResult(new CheckpointResultMessageDTO(submissionId, JudgeStatus.JUDGING.code));

            // 提交评测任务到线程池
            for (int i = 0, checkpointNum = checkpoints.size(); i < checkpointNum; ++i) {
                String checkpointId = String.valueOf(checkpoints.get(i).getCheckpointId());
                String inputPath = Paths.get(PathConfig.DATA_DIR, checkpointId + ".in").toString();
                String answerPath = Paths.get(PathConfig.DATA_DIR, checkpointId + ".ans").toString();
                String outputPath = Paths.get(userOutputDir, checkpointId + ".out").toString();

                Integer checkpointScore = checkpoints.get(i).getCheckpointScore();

                commandExecutor.submit(new IOJudgeCommand(submissionId, i, checkpointScore, timeLimit, memoryLimit, inputPath, outputPath, answerPath, runConfig));
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
            result.setUsedMemory(maxUsedTime);
            result.setJudgeLog(judgeLog);
        } finally {
            result.setJudgeLog(judgeLog);
        }
        return result;
    }

    private void compile(JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig) throws CompileErrorException {
        try {
            String srcPath = compileConfig.getSrcName();
            String code = submission.getCode();
            FileUtils.writeFile(Paths.get(workspaceDir, srcPath).toString(), code);

            log.info(String.format("Compiling \"%s\"", srcPath));

            String compilerLogPath = "compiler.out";
            String[] exeEnvs = new String[1];
            exeEnvs[0] = "PATH=" + System.getenv("PATH");

            StringBuilder sb = new StringBuilder();

            for (String eachCompileCommand : compileConfig.getCommands()) {
                String[] _commands = eachCompileCommand.split(" ");

                Argument[] _args = new Argument[10];
                _args[0] = new Argument(SandboxArgument.MAX_CPU_TIME, compileConfig.getMaxCpuTime());       /* max_cpu_time    */
                _args[1] = new Argument(SandboxArgument.MAX_REAL_TIME, compileConfig.getMaxRealTime());     /* max_real_time   */
                _args[2] = new Argument(SandboxArgument.MAX_MEMORY, compileConfig.getMaxMemory() * 1024);   /* max_memory      */
                _args[3] = new Argument(SandboxArgument.MAX_STACK, 128 * 1024 * 1024);                      /* max_stack       */
                _args[4] = new Argument(SandboxArgument.MAX_OUTPUT_SIZE, 1024 * 1024);                      /* max_output_size */
                _args[5] = new Argument(SandboxArgument.EXE_PATH, _commands[0]);                            /* exe_path        */
                _args[6] = new Argument(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(_commands, 1, _commands.length));
                _args[7] = new Argument(SandboxArgument.EXE_ENVS, exeEnvs);                                 /* exe_envs        */
                _args[8] = new Argument(SandboxArgument.INPUT_PATH, "/dev/null");                           /* input_path      */
                _args[9] = new Argument(SandboxArgument.OUTPUT_PATH, compilerLogPath);                      /* output_path     */

                SandboxResultDTO sandboxResultDTO = SandboxRunner.run(0, workspaceDir, _args);
                if (sandboxResultDTO == null) {
                    throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", eachCompileCommand));
                }

                try {
                    sb.append(FileUtils.readFile(Paths.get(workspaceDir, compilerLogPath).toString())).append("\n");
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

    private class IOJudgeCommand implements Command {

        private final long submissionId;
        private final int caseNo;
        private final int score;
        private final String outputPath;
        private final String answerPath;

        private final List<Argument[]> argsList;

        IOJudgeCommand(long submissionId, int caseNo, int score, int timeLimit, int memoryLimit, String inputPath,
                       String outputPath, String answerPath, JudgeTemplateConfigDTO.TemplateConfig.Run runConfig) throws SystemErrorException {
            this.submissionId = submissionId;
            this.caseNo = caseNo;
            this.score = score;
            this.outputPath = outputPath;
            this.answerPath = answerPath;

            argsList = new ArrayList<>();

            for (String eachCompileCommand : runConfig.getCommands()) {
                String[] _commands = eachCompileCommand.split(" ");

                Argument[] _args = new Argument[12];
                _args[0] = new Argument(SandboxArgument.MAX_CPU_TIME, timeLimit * runConfig.getMaxCpuTimeFactor());       /* max_cpu_time     */
                _args[1] = new Argument(SandboxArgument.MAX_REAL_TIME, timeLimit * runConfig.getMaxRealTimeFactor());     /* max_real_time    */
                _args[2] = new Argument(SandboxArgument.MAX_MEMORY, memoryLimit * runConfig.getMaxMemoryFactor() * 1024);          /* max_memory       */
                _args[3] = new Argument(SandboxArgument.MAX_STACK, 134217728 /* 128 * 1024 * 1024 */);      /* max_stack        */
                _args[4] = new Argument(SandboxArgument.MAX_OUTPUT_SIZE, 1048576 /* 1024 * 1024 */);        /* max_output_size  */
                _args[5] = new Argument(SandboxArgument.EXE_PATH, _commands[0]);                            /* exe_path         */
                _args[6] = new Argument(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(_commands, 1, _commands.length));
                _args[7] = new Argument(SandboxArgument.EXE_ENVS, runConfig.getEnvs());                                 /* exe_envs         */
                _args[8] = new Argument(SandboxArgument.INPUT_PATH, inputPath);                           /* input_path       */
                _args[9] = new Argument(SandboxArgument.OUTPUT_PATH, outputPath);                      /* output_path      */
                _args[10] = new Argument(SandboxArgument.UID, PathConfig.NOBODY_UID);
                _args[11] = new Argument(SandboxArgument.GID, PathConfig.NOBODY_GID);

                argsList.add(_args);
            }
        }

        @Override
        public CommandExecuteResult<CheckpointResultMessageDTO> run(int coreNo) {
            CommandExecuteResult<CheckpointResultMessageDTO> commandExecuteResult = null;
            try {
                boolean success = true;
                int maxUsedTime = 0;
                int maxUsedMemory = 0;
                for (Argument[] args : argsList) {
                    SandboxResultDTO judgeResult = SandboxRunner.run(coreNo, workspaceDir, args);
                    if (SandboxResult.SUCCESS.equals(judgeResult.getResult())) {
                        maxUsedTime = Math.max(maxUsedTime, Math.max(judgeResult.getCpuTime(), judgeResult.getRealTime()));
                        maxUsedMemory = Math.max(maxUsedMemory, judgeResult.getMemory());
                    } else if (SandboxResult.SYSTEM_ERROR.equals(judgeResult.getResult())) {
                        throw new SystemErrorException(String.format("Sandbox Internal Error #%d, signal #%d", judgeResult.getError(), judgeResult.getSignal()));
                    } else {
                        success = false;
                        commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                                submissionId, caseNo, Objects.requireNonNull(SandboxResult.of(judgeResult.getResult())).submissionJudgeResult.code,
                                0, 0, 0)
                        );
                        break;
                    }
                }
                if (success) {
                    SubmissionJudgeResult result = check();
                    if (SubmissionJudgeResult.AC.code == result.code) {
                        commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                                submissionId, caseNo, result.code, score, maxUsedTime, maxUsedMemory)
                        );
                    } else {
                        commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                                submissionId, caseNo, result.code, 0, maxUsedTime, maxUsedMemory)
                        );
                    }
                }
            } catch (SystemErrorException e) {
                log.warn("", e);
                judgeLog += e + "\n";
                commandExecuteResult = new CommandExecuteResult<>(new CheckpointResultMessageDTO(
                        submissionId, caseNo, SubmissionJudgeResult.SE.code, 0, 0, 0)
                );
            } catch (Exception e) {
                log.warn("", e);
                throw e;
            }
            log.info("case {} finish", caseNo);
            return commandExecuteResult;
        }

        private SubmissionJudgeResult check() throws SystemErrorException {
            ProcessUtils.ProcessStatus processStatus = ProcessUtils.cmd(workspaceDir, "sudo", "diff", answerPath, outputPath, "--ignore-space-change", "--ignore-blank-lines");
            return processStatus.exitCode == 0 ? SubmissionJudgeResult.AC : SubmissionJudgeResult.WA;
        }
    }
}
