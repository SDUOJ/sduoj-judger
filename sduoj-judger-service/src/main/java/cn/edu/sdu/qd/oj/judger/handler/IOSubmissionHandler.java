package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.checkpoint.dto.CheckpointManageListDTO;
import cn.edu.sdu.qd.oj.dto.FileDownloadReqDTO;
import cn.edu.sdu.qd.oj.judger.client.CheckpointClient;
import cn.edu.sdu.qd.oj.judger.client.FilesysClient;
import cn.edu.sdu.qd.oj.judger.client.ProblemClient;
import cn.edu.sdu.qd.oj.judger.command.Command;
import cn.edu.sdu.qd.oj.judger.command.CommandExecutor;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.dto.CommandExecuteResult;
import cn.edu.sdu.qd.oj.judger.dto.OneJudgeResult;
import cn.edu.sdu.qd.oj.judger.enums.JudgeStatus;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.manager.LocalCheckpointManager;
import cn.edu.sdu.qd.oj.judger.sender.RabbitSender;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateConfigDTO;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.problem.dto.ProblemCheckpointDTO;
import cn.edu.sdu.qd.oj.problem.dto.ProblemJudgerDTO;
import cn.edu.sdu.qd.oj.sandbox.service.SandboxService;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.IOUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Component;

import java.io.BufferedInputStream;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ExecutionException;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;


@Slf4j
@Component
public class IOSubmissionHandler extends SubmissionHandler {

    private String judgeLog;
    private JudgeTemplateConfigDTO judgeTemplateConfigDTO;

    @Autowired
    private SandboxService sandboxService;

    @Autowired
    private CheckpointClient checkpointClient;

    @Autowired
    private FilesysClient filesysClient;

    @Autowired
    private ProblemClient problemClient;

    @Autowired
    private CommandExecutor commandExecutor;

    @Autowired
    private RabbitSender rabbitSender;

    @Autowired
    private LocalCheckpointManager localCheckpointManager;


    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.IO;
    }

    @Override
    public SubmissionUpdateReqDTO start(JudgeTemplateDTO judgeTemplateDTO) throws CompileErrorException, SystemErrorException {
        judgeTemplateConfigDTO = JSON.parseObject(judgeTemplateDTO.getShellScript(), JudgeTemplateConfigDTO.class);

        List<CheckpointManageListDTO> checkpointManageListDTOList = checkpointClient.queryCheckpointListByProblemId(submissionMessageDTO.getProblemId());

        // 检查所有checkpoints，下载不存在的checkpoints
        List<FileDownloadReqDTO> neededCheckpoints = new ArrayList<>();
        for (CheckpointManageListDTO checkpointManageDTO : checkpointManageListDTOList.stream().filter(checkpointManageDTO -> !localCheckpointManager.isCheckpointExist(checkpointManageDTO.getCheckpointId())).collect(Collectors.toList())) {
            FileDownloadReqDTO inFile = FileDownloadReqDTO.builder()
                    .id(checkpointManageDTO.getInputFileId())
                    .downloadFilename(checkpointManageDTO.getCheckpointId() + ".in")
                    .build();
            FileDownloadReqDTO outFile = FileDownloadReqDTO.builder()
                    .id(checkpointManageDTO.getOutputFileId())
                    .downloadFilename(checkpointManageDTO.getCheckpointId() + ".ans")
                    .build();
            neededCheckpoints.add(inFile);
            neededCheckpoints.add(outFile);
        }
        try {
            Resource download = filesysClient.download(neededCheckpoints);
            ZipInputStream zipInputStream = new ZipInputStream(new BufferedInputStream(download.getInputStream()));
            ZipEntry zipEntry;
            while((zipEntry = zipInputStream.getNextEntry()) != null) {
                String name = zipEntry.getName();
                byte[] bytes = IOUtils.toByteArray(zipInputStream);
                FileUtils.writeFile(Paths.get(PathConfig.DATA_DIR, name).toString(), bytes);
            }
        } catch(Exception e) {
            throw new SystemErrorException(String.format("Can not download checkpoints:\n%s", e));
        }

        // 编译选项
        JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig = judgeTemplateConfigDTO.getUser().getCompile();
        // 运行选项
        JudgeTemplateConfigDTO.TemplateConfig.Run runConfig = judgeTemplateConfigDTO.getUser().getRun();
        // 题目配置：时间、空间、检查点分数
        ProblemJudgerDTO problemJudgerDTO = problemClient.queryProblemJudgeDTO(submissionMessageDTO.getProblemId());
        int timeLimit = problemJudgerDTO.getTimeLimit();
        int memoryLimit = problemJudgerDTO.getMemoryLimit();
        List<ProblemCheckpointDTO> checkpoints = problemJudgerDTO.getCheckpoints();

        Long submissionId = submissionMessageDTO.getSubmissionId();
        // 发送 compiling 的 websocket
        rabbitSender.sendOneJudgeResult(new OneJudgeResult(submissionId, JudgeStatus.COMPILING));
        // 编译
        compile(compileConfig);

        // 发送 juding 的 websocket
        rabbitSender.sendOneJudgeResult(new OneJudgeResult(submissionId, JudgeStatus.JUDGING));

        int checkpointNum = checkpointManageListDTOList.size();
        for (int i = 0; i < checkpointNum; ++i) {
            String checkpointId = String.valueOf(checkpointManageListDTOList.get(i).getCheckpointId());
            String inputPath = Paths.get(PathConfig.DATA_DIR, checkpointId + ".in").toString();
            String answerPath = Paths.get(PathConfig.DATA_DIR, checkpointId + ".ans").toString();
            String outputPath = Paths.get(userOutputDir, checkpointId + ".out").toString();

            Integer checkpointScore = checkpoints.get(i).getCheckpointScore();

            commandExecutor.submit(new OneJudge(i, checkpointScore, timeLimit, memoryLimit, inputPath, outputPath, answerPath, runConfig));
        }

        int maxUsedTime = 0;
        int maxUsedMemory = 0;
        int judgeScore = 0;
        SubmissionJudgeResult judgeResult = SubmissionJudgeResult.AC;
        List<List<Integer>> checkpointResults = new ArrayList<>();
        for (int i = 0; i < checkpointNum; ++i) {
            try {
                CommandExecuteResult executeResult = commandExecutor.take();
                OneJudgeResult oneJudgeResult = executeResult.toOneJudgeResult(submissionId);
                rabbitSender.sendOneJudgeResult(oneJudgeResult);

                List<Integer> resultList = executeResult.toList();
                checkpointResults.add(resultList);
                maxUsedTime = Math.max(maxUsedTime, (Integer)oneJudgeResult.getUsedTime());
                maxUsedMemory = Math.max(maxUsedMemory, (Integer)oneJudgeResult.getUsedMemory());
                judgeScore += (Integer)oneJudgeResult.getJudgeScore();
                if (SubmissionJudgeResult.AC.equals(judgeResult)) {
                    judgeResult = SubmissionJudgeResult.of((Integer)oneJudgeResult.getJudgeResult());
                }
            } catch (InterruptedException | ExecutionException e) {
                e.printStackTrace();
            }
        }
        rabbitSender.sendOneJudgeResult(new OneJudgeResult(submissionId, JudgeStatus.END));
        SubmissionUpdateReqDTO result = new SubmissionUpdateReqDTO();
        result.setCheckpointResults(checkpointResults);
        result.setJudgeResult(judgeResult.code);
        result.setJudgeScore(judgeScore);
        result.setUsedTime(maxUsedTime);
        result.setUsedMemory(maxUsedTime);
        result.setJudgeLog(judgeLog);
        result.setSubmissionId(submissionId);
        return result;
    }

    private void compile(JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig) throws CompileErrorException {
        try {
            String srcPath = compileConfig.getSrcName();
            String code = submissionMessageDTO.getCode();
            FileUtils.writeFile(srcPath, code);
            ProcessUtils.chown(srcPath, "nobody");
            ProcessUtils.chmod(srcPath, "400");

            log.info(String.format("Compiling \"%s\"", srcPath));

            String compilerLogPath = Paths.get(workspaceDir, "compiler.out").toString();
            String[] exeEnvs = new String[1];
            exeEnvs[0] = "PATH=" + System.getenv("PATH");

            StringBuilder sb = new StringBuilder();

            for (String eachCompileCommand : compileConfig.getCommands()) {
                String[] _commands = eachCompileCommand.split(" ");

                Argument[] _args = new Argument[10];
                _args[0] = new Argument(SandboxArgument.MAX_CPU_TIME, compileConfig.getMaxCpuTime());       /* max_cpu_time     */
                _args[1] = new Argument(SandboxArgument.MAX_REAL_TIME, compileConfig.getMaxRealTime());     /* max_real_time    */
                _args[2] = new Argument(SandboxArgument.MAX_MEMORY, compileConfig.getMaxMemory() * 1024);          /* max_memory       */
                _args[3] = new Argument(SandboxArgument.MAX_STACK, 134217728 /* 128 * 1024 * 1024 */);      /* max_stack        */
                _args[4] = new Argument(SandboxArgument.MAX_OUTPUT_SIZE, 1048576 /* 1024 * 1024 */);        /* max_output_size  */
                _args[5] = new Argument(SandboxArgument.EXE_PATH, _commands[0]);                            /* exe_path         */
                _args[6] = new Argument(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(_commands, 1, _commands.length));
                _args[7] = new Argument(SandboxArgument.EXE_ENVS, exeEnvs);                                 /* exe_envs         */
                _args[8] = new Argument(SandboxArgument.INPUT_PATH, "/dev/null");                           /* input_path       */
                _args[9] = new Argument(SandboxArgument.OUTPUT_PATH, compilerLogPath);                      /* output_path      */

                SandboxResultDTO sandboxResultDTO = sandboxService.run(0, _args);
                if (sandboxResultDTO == null) {
                    throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", eachCompileCommand));
                }

                try {
                    sb.append(FileUtils.readFile(compilerLogPath)).append("\n");
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

    private class OneJudge implements Command {

        private final int caseNo;
        private final int score;
        private final String outputPath;
        private final String answerPath;

        private final List<Argument[]> argsList;

        OneJudge(int caseNo, int score, long timeLimit, long memoryLimit, String inputPath, String outputPath, String answerPath, JudgeTemplateConfigDTO.TemplateConfig.Run runConfig) throws SystemErrorException {
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
        public CommandExecuteResult run(int coreNo) {
            CommandExecuteResult commandExecuteResult = null;
            try {
                boolean success = true;
                int maxUsedTime = 0;
                int maxUsedMemory = 0;
                for (Argument[] args : argsList) {
                    SandboxResultDTO judgeResult = sandboxService.run(coreNo, args);
                    if (SandboxResult.SUCCESS.equals(judgeResult.getResult())) {
                        maxUsedTime = Math.max(maxUsedTime, judgeResult.getRealTime());
                        maxUsedMemory = Math.max(maxUsedMemory, judgeResult.getMemory());
                    } else if (SandboxResult.SYSTEM_ERROR.equals(judgeResult.getResult())) {
                        success = false;
                        throw new SystemErrorException(String.format("Sandbox Internal Error #%d, signal #%d", judgeResult.getError(), judgeResult.getSignal()));
                    } else {
                        success = false;
                        commandExecuteResult = new IOOneJudgeResult(
                                Objects.requireNonNull(SandboxResult.of(judgeResult.getResult())).submissionJudgeResult,
                                0, 0, 0, caseNo
                        );
                        break;
                    }
                }
                if (success) {
                    SubmissionJudgeResult result = check();
                    if (SubmissionJudgeResult.AC.code == result.code) {
                        commandExecuteResult = new IOOneJudgeResult(result, score, maxUsedTime, maxUsedMemory, caseNo);
                    } else {
                        commandExecuteResult = new IOOneJudgeResult(result, 0, maxUsedTime, maxUsedMemory, caseNo);
                    }
                }
            } catch (SystemErrorException e) {
                e.printStackTrace();
                judgeLog += e + "\n";
                commandExecuteResult = new IOOneJudgeResult(SubmissionJudgeResult.SE, 0, 0, 0, caseNo);
            }
            return commandExecuteResult;
        }

        private SubmissionJudgeResult check() throws SystemErrorException {
            ProcessUtils.ProcessStatus processStatus = ProcessUtils.cmd("diff", answerPath, outputPath, "--ignore-space-change", "--ignore-blank-lines");
            return processStatus.exitCode == 0 ? SubmissionJudgeResult.AC : SubmissionJudgeResult.WA;
        }
    }

    @Getter
    @Setter
    @AllArgsConstructor
    @NoArgsConstructor
    private static class IOOneJudgeResult extends CommandExecuteResult {
        private SubmissionJudgeResult judgeResult;
        private int judgeScore;
        private int usedTime;
        private int usedMemory;
        private int caseNo;

        public OneJudgeResult toOneJudgeResult(Long submissionId) {
            return new OneJudgeResult(submissionId, caseNo, judgeResult.code, judgeScore, usedTime, usedMemory / 1024);
        }

        public List<Integer> toList() {
            return Lists.newArrayList(judgeResult.code, usedTime, usedMemory);
        }
    }
}
