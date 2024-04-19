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
import cn.edu.sdu.qd.oj.common.rpc.client.FilesysClient;
import cn.edu.sdu.qd.oj.common.rpc.client.JudgeTemplateClient;
import cn.edu.sdu.qd.oj.common.rpc.client.ProblemClient;
import cn.edu.sdu.qd.oj.common.rpc.client.SubmissionClient;
import cn.edu.sdu.qd.oj.filesys.dto.FileDownloadReqDTO;
import cn.edu.sdu.qd.oj.judger.command.CpuAffinityThreadPool;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.manager.LocalCheckerManager;
import cn.edu.sdu.qd.oj.judger.manager.LocalCheckpointManager;
import cn.edu.sdu.qd.oj.judger.manager.LocalZipManager;
import cn.edu.sdu.qd.oj.judger.sender.RabbitSender;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judger.util.ShellUtils;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.problem.dto.ProblemJudgerDTO;
import cn.edu.sdu.qd.oj.submission.api.message.CheckpointResultMsgDTO;
import cn.edu.sdu.qd.oj.submission.dto.SubmissionJudgeDTO;
import cn.edu.sdu.qd.oj.submission.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submission.enums.SubmissionJudgeResult;
import feign.Response;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.amqp.AmqpException;
import org.springframework.beans.factory.annotation.Autowired;

import java.io.BufferedInputStream;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * define default actions for submission handler
 *
 * @author zhangt2333
 */
@Slf4j
public abstract class AbstractSubmissionHandler {

    protected static final int MAX_JUDGE_LOG = 60 * 1024;

    @Autowired
    protected JudgeTemplateClient judgeTemplateClient;

    @Autowired
    protected ProblemClient problemClient;

    @Autowired
    protected FilesysClient filesysClient;

    @Autowired
    private SubmissionClient submissionClient;

    @Autowired
    protected LocalCheckpointManager localCheckpointManager;

    @Autowired
    protected LocalZipManager localZipManager;

    @Autowired
    protected LocalCheckerManager localCheckerManager;

    @Autowired
    protected RabbitSender rabbitSender;

    @Autowired
    protected CpuAffinityThreadPool cpuAffinityThreadPool;

    protected SubmissionJudgeDTO submission;

    protected JudgeTemplateDTO judgeTemplate;

    protected String workspaceDir;

    protected String userOutputDir;

    protected ProblemJudgerDTO problem;

    protected List<CheckpointJudgerDTO> checkpoints;

    protected List<CheckpointJudgerDTO> publicCheckpoints;

    protected String judgeLog;

    protected static final Pattern WHITESPACE_PATTERN = Pattern.compile("\\s+");

    public abstract JudgeTemplateTypeEnum getSupportJudgeTemplateType();

    /**
    * @Description 子类需要实现的具体评测逻辑
    * @return cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO
    **/
    protected abstract SubmissionUpdateReqDTO start() throws CompileErrorException, SystemErrorException ;

    public void handle(SubmissionJudgeDTO submissionJudgeDTO, JudgeTemplateDTO judgeTemplateDTO) throws Throwable {
        // 清空上次评测残留
        this.submission = null;
        this.judgeTemplate = null;
        this.workspaceDir = null;
        this.userOutputDir = null;
        this.problem = null;
        this.checkpoints = null;
        this.judgeLog = null;


        this.submission = submissionJudgeDTO;
        this.judgeTemplate = judgeTemplateDTO;
        SubmissionUpdateReqDTO updateReqDTO = null;
        try {
            // 初始化用户空间
            initializeWorkspace();
            // 下载用户提交文件
            initializeSubmission();
            // 下载评测模板支撑文件
            initializeJudgeTemplate();
            // 初始化题目配置
            initializeProblem();
            // 下载检查点
            initializeCheckpoint();
            // 处理 function template
            handleFunctionTemplate();
            // 调用子类实现的评测逻辑
            updateReqDTO = this.start();

            // 释放用户空间
            releaseWorkspace();
        } catch (CompileErrorException e) {
            updateReqDTO = SubmissionUpdateReqDTO.builder()
                    .submissionId(submission.getSubmissionId())
                    .judgeResult(SubmissionJudgeResult.CE.code)
                    .judgeScore(0)
                    .usedTime(0)
                    .usedMemory(0)
                    .judgeLog(e.getMessage())
                    .build();
        } catch (SystemErrorException | OutOfMemoryError e) {
            log.error("", e);
            updateReqDTO = SubmissionUpdateReqDTO.builder()
                    .submissionId(submission.getSubmissionId())
                    .judgeResult(SubmissionJudgeResult.SE.code)
                    .judgeScore(0)
                    .usedTime(0)
                    .usedMemory(0)
                    .judgeLog(e.getMessage())
                    .build();
        } catch (Throwable t) {
            log.error("", t);
            throw t;
        }
        // 更新 result 并 ack
        if (updateReqDTO != null) {
            // 设置 updateDTO 中的乐观锁字段
            updateReqDTO.setVersion(submission.getVersion());
            // 传给后端的 judgeLog 字段限制长度
            String judgeLog = updateReqDTO.getJudgeLog();
            if (StringUtils.isNotBlank(judgeLog) && judgeLog.length() > MAX_JUDGE_LOG) {
                updateReqDTO.setJudgeLog(judgeLog.substring(0, MAX_JUDGE_LOG));
            }
            // 多次尝试
            for (int i = 0; i < 5; i++) {
                try {
                    // 更新 submission result
                    submissionClient.update(updateReqDTO);

                    // 发送 end 的 websocket
                    CheckpointResultMsgDTO messageDTO = new CheckpointResultMsgDTO(
                            updateReqDTO.getSubmissionId(),
                            submission.getVersion(),
                            SubmissionJudgeResult.END.code,
                            updateReqDTO.getJudgeResult(),
                            updateReqDTO.getJudgeScore(),
                            updateReqDTO.getUsedTime(),
                            updateReqDTO.getUsedMemory()
                    );
                    rabbitSender.sendOneJudgeResult(messageDTO);
                    break;
                } catch (AmqpException e) {
                    log.warn("sendOneJudgeResult", e);
                    try {
                        Thread.sleep(i * 2000L);
                    } catch (Throwable ignore) {
                    }
                } catch (Throwable t) {
                    log.error("sendOneJudgeResult", t);
                    throw t;
                }
            }
        }
    }

    /**
     * 将functionTempate和用户代码拼接，成为真正要测的代码
     */
    private void handleFunctionTemplate() {
        Long judgeTemplateId = judgeTemplate.getId();
        problem.getFunctionTemplates()
               .stream()
               .filter(ft -> Objects.equals(ft.getJudgeTemplateId(), judgeTemplateId))
               .findFirst()
               .ifPresent(ft -> {
                   submission.setCode(ft.getFunctionTemplate() + "\n" + submission.getCode());
               });
    }

    private void initializeWorkspace() throws SystemErrorException {
        workspaceDir = Paths.get(PathConfig.WORKSPACE_DIR, String.valueOf(submission.getSubmissionId())).toString();
        userOutputDir = Paths.get(workspaceDir, "output").toString();
        try {
            ShellUtils.deleteWorkspaceDir(workspaceDir);
            FileUtils.createDir(workspaceDir);
            FileUtils.createDir(userOutputDir);
            ShellUtils.chown(workspaceDir, "nobody:nogroup");
            ShellUtils.chmod(workspaceDir, "777");
        } catch (Exception e) {
            throw new SystemErrorException("Can not initialize workspace:\n" + e);
        }
    }

    private void releaseWorkspace() throws SystemErrorException {
        try {
            ShellUtils.chmod(workspaceDir, "711");
            // clears the workspace of non-rejudged submission to save storage
            if (submission.getVersion() == 0) {
                ShellUtils.deleteWorkspaceDir(workspaceDir);
            }
        } catch (Exception e) {
            throw new SystemErrorException("Can not release workspace:\n" + e.toString());
        }
    }

    private void initializeSubmission() throws SystemErrorException {
        Long zipFileId = submission.getZipFileId();
        if (zipFileId == null || localZipManager.isExist(zipFileId)) {
            return;
        }
        downloadZipFile(zipFileId);
        localZipManager.addZipFile(zipFileId);
    }

    private void initializeJudgeTemplate() throws SystemErrorException {
        Long zipFileId = judgeTemplate.getZipFileId();
        if (zipFileId == null || localZipManager.isExist(zipFileId)) {
            return;
        }
        downloadZipFile(zipFileId);
        localZipManager.addZipFile(zipFileId);
    }

    private void downloadZipFile(long zipFileId) throws SystemErrorException {
        File file = Paths.get(PathConfig.ZIP_DIR, zipFileId + ".zip").toFile();
        if (!file.exists()) {
            Path tempFilePath = Paths.get(PathConfig.ZIP_DIR,
                    "tmp-" + UUID.randomUUID().toString().replace("-", ""));
            try {
                Response resp = filesysClient.download(zipFileId);
                Files.copy(resp.body().asInputStream(), tempFilePath,
                        StandardCopyOption.REPLACE_EXISTING);
                resp.close();
                if (!file.exists()) {
                    log.info("\nDownloaded zip {} at {}, now moving to {}",
                            zipFileId, tempFilePath, file);
                    try {
                        Files.move(tempFilePath, file.toPath(),
                                StandardCopyOption.ATOMIC_MOVE);
                    } catch (Exception e) {
                        if (!file.exists()) {
                            log.error("Can not move zip file", e);
                            throw e;
                        }
                    }
                }
            } catch (Exception e) {
                throw new SystemErrorException(String.format(
                        "Can not download Zip %s: %s", zipFileId, e));
            } finally {
                File tempFile = tempFilePath.toFile();
                if (tempFile.exists() && !tempFile.delete()) {
                    log.warn("Can not delete temp file {}", tempFile);
                }
            }
        }
    }

    private void initializeProblem() throws SystemErrorException {
        // 查询题目配置
        try {
            problem = problemClient.queryProblemJudgeDTO(submission.getProblemId());
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not query problem:\n%s", e));
        }
    }

    private void initializeCheckpoint() throws SystemErrorException {
        // 查询出题目的检查点
        try {
            checkpoints = problemClient.listJudgerCheckpoints(submission.getProblemId());
            publicCheckpoints = problemClient.listJudgerPublicCheckpoints(submission.getProblemId());
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not query checkpoint:\n%s", e));
        }
        // 检查所有checkpoints，找出本地没有的检查点
        Collection<CheckpointJudgerDTO> checkpointsToDownload  = Stream
                .concat(checkpoints.stream(), publicCheckpoints.stream())
                .filter(o -> !localCheckpointManager.isCheckpointExist(o.getCheckpointId()))
                .collect(Collectors.toMap(CheckpointJudgerDTO::getCheckpointId,
                        Function.identity(), (o1, o2) -> o1))
                .values();
        // 下载不存在的checkpoints
        for (CheckpointJudgerDTO checkpoint : checkpointsToDownload) {
            List<FileDownloadReqDTO> fileDownloadReqList = new ArrayList<>();
            fileDownloadReqList.add(new FileDownloadReqDTO(
                    checkpoint.getInputFileId(),
                    checkpoint.getCheckpointId() + ".in"
            ));
            fileDownloadReqList.add(new FileDownloadReqDTO(
                    checkpoint.getOutputFileId(),
                    checkpoint.getCheckpointId() + ".ans"
            ));
            try {
                log.info("\nDownloadCheckpoint: {}", checkpointsToDownload
                        .stream()
                        .map(CheckpointJudgerDTO::getCheckpointId)
                        .collect(Collectors.toList()));
                // 下载检查点并解压，维护本地已有 checkpoints
                Response resp = filesysClient.zipDownload(fileDownloadReqList);
                ZipInputStream zipInputStream = new ZipInputStream(new BufferedInputStream(
                        resp.body().asInputStream()
                ));
                ZipEntry zipEntry;
                while ((zipEntry = zipInputStream.getNextEntry()) != null) {
                    String name = zipEntry.getName();
                    // do not read from zipInputStream directly
                    // it will cause the zipInputStream to be closed
                    byte[] bytes = zipInputStream.readAllBytes();
                    FileUtils.writeFile(Paths.get(PathConfig.DATA_DIR, name), bytes);
                    localCheckpointManager.addCheckpoint(Long.valueOf(name.substring(0, name.indexOf("."))));
                }
                resp.close();
            } catch (Exception e) {
                log.error("Can not download checkpoints", e);
                throw new SystemErrorException("Can not download checkpoints");
            }
        }
    }


    public static final Pattern PATTERN_PROBLEM_CONFIG = Pattern.compile("(\\{problemTimeLimit\\}|\\{problemMemoryLimit\\})");
    /**
    * @Description 字符串中模板替换成题目配置
    * support: {problemTimeLimit}, {problemMemoryLimit}
    **/
    protected String replacePatternToProblemInfo(String str) {
        if (StringUtils.isBlank(str)) {
            return str;
        }
        Matcher matcher = PATTERN_PROBLEM_CONFIG.matcher(str);
        StringBuffer sb = new StringBuffer();
        while (matcher.find()) {
            // 值多的话换成 map
            switch (matcher.group(1)) {
                case "{problemTimeLimit}":
                    matcher.appendReplacement(sb, problem.getTimeLimit().toString());
                    break;
                case "{problemMemoryLimit}":
                    matcher.appendReplacement(sb, problem.getMemoryLimit().toString());
                    break;
            }
        }
        matcher.appendTail(sb);
        return sb.toString();
    }

    protected String[] replacePatternToProblemInfo(String[] strs) {
        for (int i = 0; i < strs.length; i++) {
            strs[i] = replacePatternToProblemInfo(strs[i]);
        }
        return strs;
    }
}
