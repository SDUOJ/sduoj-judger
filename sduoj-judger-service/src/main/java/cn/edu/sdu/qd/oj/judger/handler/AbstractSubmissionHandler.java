package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.checkpoint.dto.CheckpointManageListDTO;
import cn.edu.sdu.qd.oj.common.util.CollectionUtils;
import cn.edu.sdu.qd.oj.dto.FileDownloadReqDTO;
import cn.edu.sdu.qd.oj.judger.client.*;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.manager.LocalCheckpointManager;
import cn.edu.sdu.qd.oj.judger.manager.LocalZipManager;
import cn.edu.sdu.qd.oj.judger.sender.RabbitSender;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.problem.dto.ProblemJudgerDTO;
import cn.edu.sdu.qd.oj.submit.dto.CheckpointResultMessageDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionJudgeDTO;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import com.google.common.collect.Lists;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.IOUtils;
import org.apache.commons.lang3.StringUtils;
import org.springframework.amqp.AmqpException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.Resource;

import java.io.BufferedInputStream;
import java.io.File;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

@Slf4j
public abstract class AbstractSubmissionHandler {

    @Autowired
    protected JudgeTemplateClient judgeTemplateClient;

    @Autowired
    protected ProblemClient problemClient;

    @Autowired
    protected CheckpointClient checkpointClient;

    @Autowired
    protected FilesysClient filesysClient;

    @Autowired
    private SubmissionClient submissionClient;

    @Autowired
    protected LocalCheckpointManager localCheckpointManager;

    @Autowired
    protected LocalZipManager localZipManager;

    @Autowired
    protected RabbitSender rabbitSender;

    protected SubmissionJudgeDTO submission;

    protected JudgeTemplateDTO judgeTemplate;

    protected String workspaceDir;

    protected String userOutputDir;

    protected ProblemJudgerDTO problem;

    protected List<CheckpointManageListDTO> checkpoints;

    public abstract JudgeTemplateTypeEnum getSupportJudgeTemplateType();

    /**
    * @Description 子类需要实现的具体评测逻辑
    * @return cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO
    **/
    protected abstract SubmissionUpdateReqDTO start() throws CompileErrorException, SystemErrorException ;

    public void handle(SubmissionJudgeDTO submissionJudgeDTO, JudgeTemplateDTO judgeTemplateDTO) throws Throwable {
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
            // judgeLog 字段长度限制
            String judgeLog = updateReqDTO.getJudgeLog();
            if (StringUtils.isNotBlank(judgeLog)) {
                updateReqDTO.setJudgeLog(judgeLog.substring(0, Math.min(judgeLog.length(), 48 * 1024))); // 限制 48K judgeLog
            }
            // 多次尝试
            for (int i = 0; i < 5; i++) {
                try {
                    // 更新 submission result
                    submissionClient.update(updateReqDTO);

                    // 发送 end 的 websocket
                    CheckpointResultMessageDTO messageDTO = new CheckpointResultMessageDTO(
                            submission.getSubmissionId(),
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

    private void initializeWorkspace() throws SystemErrorException {
        workspaceDir = Paths.get(PathConfig.WORKSPACE_DIR, String.valueOf(submission.getSubmissionId())).toString();
        userOutputDir = Paths.get(workspaceDir, "output").toString();
        try {
            ProcessUtils.deleteWorkspaceDir(workspaceDir);
            FileUtils.createDir(workspaceDir);
            FileUtils.createDir(userOutputDir);
            ProcessUtils.chown(workspaceDir, "nobody");
            ProcessUtils.chmod(workspaceDir, "717");
        } catch (Exception e) {
            throw new SystemErrorException("Can not initialize workspace:\n" + e.toString());
        }
    }

    private void releaseWorkspace() throws SystemErrorException {
        try {
            ProcessUtils.chmod(workspaceDir + "/*", "711");
            // TODO: 考虑删除文件
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
    }

    private void initializeJudgeTemplate() throws SystemErrorException {
        Long zipFileId = judgeTemplate.getZipFileId();
        if (zipFileId == null || localZipManager.isExist(zipFileId)) {
            return;
        }
        downloadZipFile(zipFileId);
    }

    private void downloadZipFile(long zipFileId) throws SystemErrorException {
        try {
            Resource resource = filesysClient.download(zipFileId);
            File file = new File(Paths.get(PathConfig.ZIP_DIR, zipFileId + ".zip").toString());
            org.apache.commons.io.FileUtils.copyInputStreamToFile(resource.getInputStream(), file);
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not download Zip:%s \n%s", zipFileId, e));
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
            checkpoints = Optional.ofNullable(checkpointClient.queryCheckpointListByProblemId(submission.getProblemId()))
                    .filter(CollectionUtils::isNotEmpty)
                    .orElse(Lists.newArrayList());
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not query checkpoint:\n%s", e));
        }
        // 检查所有checkpoints，找出本地没有的检查点
        List<CheckpointManageListDTO> neededCheckpoint = checkpoints.stream()
                .filter(o -> !localCheckpointManager.isCheckpointExist(o.getCheckpointId()))
                .collect(Collectors.toList());
        List<FileDownloadReqDTO> fileDownloadReqList = new ArrayList<>();
        for (CheckpointManageListDTO checkpointManageDTO : neededCheckpoint) {
            fileDownloadReqList.add(FileDownloadReqDTO.builder()
                    .id(checkpointManageDTO.getInputFileId())
                    .downloadFilename(checkpointManageDTO.getCheckpointId() + ".in")
                    .build());
            fileDownloadReqList.add(FileDownloadReqDTO.builder()
                    .id(checkpointManageDTO.getOutputFileId())
                    .downloadFilename(checkpointManageDTO.getCheckpointId() + ".ans")
                    .build());
        }
        // 下载不存在的checkpoints
        if (CollectionUtils.isNotEmpty(fileDownloadReqList)) {
            try {
                log.info("\nDownloadCheckpoint: {}", neededCheckpoint.stream().map(CheckpointManageListDTO::getCheckpointId).collect(Collectors.toList()));
                // 下载检查点并解压，维护本地已有 checkpoints
                Resource download = filesysClient.download(fileDownloadReqList);
                ZipInputStream zipInputStream = new ZipInputStream(new BufferedInputStream(download.getInputStream()));
                ZipEntry zipEntry;
                while ((zipEntry = zipInputStream.getNextEntry()) != null) {
                    String name = zipEntry.getName();
                    byte[] bytes = IOUtils.toByteArray(zipInputStream);
                    FileUtils.writeFile(Paths.get(PathConfig.DATA_DIR, name).toString(), bytes);

                    localCheckpointManager.addCheckpoint(Long.valueOf(name.substring(0, name.indexOf("."))));
                }
            } catch (Exception e) {
                throw new SystemErrorException(String.format("Can not download checkpoints:\n%s", e));
            }
        }
    }
}
