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

import com.sduoj.common.rpc.client.FilesysClient;
import com.sduoj.common.util.JsonUtils;
import com.sduoj.filesys.dto.TaskOutputUploadDTO;
import com.sduoj.judger.client.RunClient;
import com.sduoj.judger.config.CpuConfig;
import com.sduoj.judger.config.PathConfig;
import com.sduoj.judger.manager.LocalCheckerManager;
import com.sduoj.judger.util.ProcessUtils;
import com.sduoj.judger.util.WorkspaceFiles;
import com.sduoj.judgetemplate.dto.JudgeTemplateConfigDTO;
import com.sduoj.problem.dto.ProblemCheckerConfigDTO;
import com.sduoj.sandbox.dto.SandboxResultDTO;
import com.sduoj.sandbox.enums.SandboxResult;
import com.sduoj.submission.dto.*;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;
import java.util.zip.ZipInputStream;

/** Single-use workspace, compile once, sequential cases. No formal checkpoint access. */
@Component
@ConditionalOnProperty(name = "sduoj.run.worker", havingValue = "true")
@RequiredArgsConstructor
@Slf4j
public class CasesRunHandler {
    private final RunClient client;
    private final LocalCheckerManager checkers;
    private final FilesysClient files;
    private static final Pattern SPACE = Pattern.compile("\\s+");

    public void execute(RunSpecDTO spec) throws Exception {
        long id = spec.getSubmission().getSubmissionId();
        int version = spec.getSubmission().getVersion();
        Path workspace = Paths.get(PathConfig.WORKSPACE_DIR, "run-" + id + "-" + version);
        List<RunCaseResultItemDTO> results = new ArrayList<>();
        RunTaskUpdateReqDTO update = new RunTaskUpdateReqDTO();
        update.setSubmissionId(id);
        update.setVersion(version);
        int aggregate = -1;
        String judgeLog = "";
        boolean management = spec.getTaskType() != null && spec.getTaskType() > 100;
        Instant deadline = Instant.now().plusSeconds(management ? 95 : 8L * spec.getCases().size());
        Path validatorDirectory = workspace.resolve(".validator-" + UUID.randomUUID());
        try {
            Files.createDirectories(workspace);
            ProcessUtils.execCmd(
                    List.of("sudo", "chmod", "777", workspace.toString()),
                    null,
                    workspace.toFile(),
                    5,
                    TimeUnit.SECONDS);
            JudgeTemplateConfigDTO config =
                    JsonUtils.toObject(
                            spec.getJudgeTemplate().getShellScript(), JudgeTemplateConfigDTO.class);
            if (config == null || config.getUser() == null)
                throw new IllegalArgumentException("Invalid execution template");
            String code = spec.getSubmission().getCode();
            if (spec.getSubmission().getZipFileId() != null) {
                byte[] zip = download(spec.getSubmission().getZipFileId(), 5 * 1024 * 1024);
                if (!HexFormat.of()
                        .formatHex(MessageDigest.getInstance("SHA-256").digest(zip))
                        .equals(spec.getProgramZipSha256())) {
                    throw new IllegalStateException("ZIP snapshot changed");
                }
                extractZip(zip, workspace);
            }
            if (code != null
                    && !Integer.valueOf(101).equals(spec.getTaskType())
                    && spec.getProblem().getFunctionTemplates() != null) {
                code =
                        spec.getProblem().getFunctionTemplates().stream()
                                        .filter(
                                                ft ->
                                                        Objects.equals(
                                                                ft.getJudgeTemplateId(),
                                                                spec.getSubmission()
                                                                        .getJudgeTemplateId()))
                                        .map(ft -> ft.getFunctionTemplate() + "\n")
                                        .findFirst()
                                        .orElse("")
                                + code;
            }
            JudgeTemplateConfigDTO.TemplateConfig.Compile compile = config.getUser().getCompile();
            Path source = workspace.resolve(compile.getSrcName()).normalize();
            if (!source.startsWith(workspace))
                throw new IllegalArgumentException("Invalid template source path");
            if (code != null) Files.writeString(source, code);
            else if (!Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS))
                throw new IllegalArgumentException("ZIP does not contain template source file");
            for (String command : compile.getCommands()) {
                if (Instant.now().isAfter(deadline))
                    throw new IllegalStateException("Run deadline exceeded");
                if (!client.active(id, version)) return;
                SandboxResultDTO compiled =
                        sandbox(
                                workspace,
                                substitute(command, spec),
                                Math.min(10000, compile.getMaxCpuTime()),
                                Math.min(15000, compile.getMaxRealTime()),
                                compile.getMaxMemory() * 1024L,
                                null,
                                "/dev/null",
                                "compile.out",
                                "compile.err",
                                16 * 1024 * 1024,
                                false,
                                null,
                                deadline);
                judgeLog =
                        prefix(workspace.resolve("compile.out"), 32768)
                                + prefix(workspace.resolve("compile.err"), 24576);
                if (compiled == null || compiled.getResult() != 0 || compiled.getExitCode() != 0) {
                    update.setComplete(true);
                    update.setJudgeResult(8);
                    update.setJudgeLog(judgeLog);
                    update.setResults(results);
                    client.update(update);
                    return;
                }
            }

            JudgeTemplateConfigDTO.TemplateConfig.Run run = config.getUser().getRun();
            for (int i = 0; i < spec.getCases().size(); i++) {
                if (!client.active(id, version)) return;
                if (Instant.now().isAfter(deadline))
                    throw new IllegalStateException("Run execution deadline exceeded");
                RunCaseInputDTO input = spec.getCases().get(i);
                String in = i + ".in", out = i + ".out", err = i + ".err";
                if (management) {
                    var meta = spec.getMetaCases().get(i);
                    Files.write(
                            workspace.resolve(in),
                            download(meta.getInputFileId(), 5 * 1024 * 1024));
                    if (Integer.valueOf(102).equals(spec.getTaskType())) {
                        input.setExpectedOutput(
                                StandardCharsets.UTF_8
                                        .newDecoder()
                                        .decode(
                                                java.nio.ByteBuffer.wrap(
                                                        download(
                                                                meta.getOutputFileId(),
                                                                5 * 1024 * 1024)))
                                        .toString());
                    }
                } else {
                    Files.writeString(workspace.resolve(in), input.getInput());
                }
                if (Integer.valueOf(103).equals(spec.getTaskType())) {
                    int validated =
                            validateInput(workspace, validatorDirectory, spec, in, err, deadline);
                    if (validated != 1) {
                        results.add(
                                RunCaseResultItemDTO.builder()
                                        .index(i)
                                        .inputFileId(spec.getMetaCases().get(i).getInputFileId())
                                        .judgeResult(validated)
                                        .usedTime(0)
                                        .usedMemory(0)
                                        .exitCode(1)
                                        .stdout("")
                                        .stderr(
                                                prefix(
                                                        workspace.resolve(err),
                                                        spec.getStderrPrefixBytes()))
                                        .build());
                        aggregate = validated;
                        update.setResults(results);
                        update.setComplete(false);
                        if (!client.update(update)) return;
                        continue;
                    }
                }
                int time =
                        Math.min(
                                5000, spec.getProblem().getTimeLimit() * run.getMaxCpuTimeFactor());
                int real =
                        Math.min(
                                8000,
                                spec.getProblem().getTimeLimit() * run.getMaxRealTimeFactor());
                SandboxResultDTO executed =
                        sandbox(
                                workspace,
                                substitute(run.getCommand(), spec),
                                time,
                                real,
                                Math.min(
                                        512L * 1024 * 1024,
                                        spec.getProblem().getMemoryLimit()
                                                * run.getMaxMemoryFactor()
                                                * 1024L),
                                run.getSeccompRule(),
                                in,
                                out,
                                err,
                                65536,
                                true,
                                run.getEnvs(),
                                deadline);
                if (executed == null) throw new IllegalStateException("Missing sandbox result");
                int result = SandboxResult.of(executed.getResult()).submissionJudgeResult.code;
                if (Integer.valueOf(101).equals(spec.getTaskType())
                        && executed.getExitCode() != 0) {
                    result = 6;
                }
                if (executed.getResult() == 0) {
                    result =
                            Integer.valueOf(101).equals(spec.getTaskType())
                                    ? 1
                                    : input.getExpectedOutput() == null
                                            ? -1
                                            : compare(workspace, spec, input, in, out, i, deadline);
                }
                Long generatedOutput = null;
                if (Integer.valueOf(103).equals(spec.getTaskType()) && result == -1) {
                    input.setExpectedOutput(
                            StandardCharsets.UTF_8
                                    .newDecoder()
                                    .decode(
                                            java.nio.ByteBuffer.wrap(
                                                    Files.readAllBytes(workspace.resolve(out))))
                                    .toString());
                    result = compare(workspace, spec, input, in, out, i, deadline);
                    if (result == 1 && client.active(id, version)) {
                        generatedOutput =
                                files.uploadTaskOutput(
                                        new TaskOutputUploadDTO(
                                                id,
                                                version,
                                                i,
                                                Files.readAllBytes(workspace.resolve(out))));
                        if (generatedOutput == null || generatedOutput <= 0)
                            throw new IllegalStateException("Generated output upload failed");
                    }
                }
                long stdoutSize = size(workspace.resolve(out)),
                        stderrSize = size(workspace.resolve(err));
                RunCaseResultItemDTO item =
                        RunCaseResultItemDTO.builder()
                                .index(i)
                                .inputFileId(
                                        management
                                                ? spec.getMetaCases().get(i).getInputFileId()
                                                : null)
                                .outputFileId(
                                        Integer.valueOf(103).equals(spec.getTaskType())
                                                ? generatedOutput
                                                : management
                                                        ? spec.getMetaCases()
                                                                .get(i)
                                                                .getOutputFileId()
                                                        : null)
                                .checkpointId(
                                        management
                                                ? spec.getMetaCases().get(i).getCheckpointId()
                                                : null)
                                .temporaryOutput(generatedOutput != null)
                                .judgeResult(result)
                                .usedTime(Math.max(executed.getCpuTime(), executed.getRealTime()))
                                .usedMemory(executed.getMemory())
                                .exitCode(executed.getExitCode())
                                .stdout(prefix(workspace.resolve(out), spec.getStdoutPrefixBytes()))
                                .stderr(prefix(workspace.resolve(err), spec.getStderrPrefixBytes()))
                                .stdoutTruncated(stdoutSize > spec.getStdoutPrefixBytes())
                                .stderrTruncated(stderrSize > spec.getStderrPrefixBytes())
                                .stdoutOriginalLength((int) Math.min(Integer.MAX_VALUE, stdoutSize))
                                .stderrOriginalLength((int) Math.min(Integer.MAX_VALUE, stderrSize))
                                .build();
                results.add(item);
                if (result != -1 && (aggregate == -1 || aggregate == 1)) aggregate = result;
                update.setResults(results);
                update.setComplete(false);
                if (!client.update(update)) return;
            }
        } catch (Exception e) {
            aggregate = 5;
            judgeLog = e.getClass().getSimpleName() + ": " + e.getMessage();
        } finally {
            try {
                WorkspaceFiles.delete(workspace);
            } catch (Exception cleanupFailure) {
                // Preserve the task outcome; scheduled retention retries abandoned directories.
                log.warn("Run workspace cleanup failed for {}", id, cleanupFailure);
            }
        }
        update.setComplete(true);
        update.setJudgeResult(aggregate);
        update.setJudgeLog(judgeLog);
        update.setResults(results);
        client.update(update);
    }

    private byte[] download(Long id, int maxBytes) {
        var downloaded = files.byteDownloads(List.of(id), (long) maxBytes);
        if (downloaded == null || downloaded.size() != 1 || downloaded.get(0).getBytes() == null)
            throw new IllegalStateException("Missing task input file");
        byte[] data = downloaded.get(0).getBytes();
        if (data.length > maxBytes) throw new IllegalArgumentException("Task input file too large");
        return data;
    }

    public static void extractZip(byte[] archive, Path workspace) throws Exception {
        long total = 0;
        int count = 0;
        try (var zip = new ZipInputStream(new ByteArrayInputStream(archive))) {
            java.util.zip.ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (++count > 256) throw new IllegalArgumentException("ZIP has too many entries");
                Path destination = workspace.resolve(entry.getName()).normalize();
                if (!destination.startsWith(workspace) || destination.equals(workspace))
                    throw new IllegalArgumentException("Unsafe ZIP path");
                if (entry.isDirectory()) {
                    Files.createDirectories(destination);
                    continue;
                }
                Files.createDirectories(destination.getParent());
                try (var output =
                        Files.newOutputStream(destination, StandardOpenOption.CREATE_NEW)) {
                    byte[] buffer = new byte[8192];
                    int size;
                    while ((size = zip.read(buffer)) != -1) {
                        total += size;
                        if (total > 16 * 1024 * 1024)
                            throw new IllegalArgumentException("ZIP expansion exceeds limit");
                        output.write(buffer, 0, size);
                    }
                }
            }
        }
    }

    private int validateInput(
            Path workspace,
            Path directory,
            RunSpecDTO spec,
            String in,
            String err,
            Instant deadline)
            throws Exception {
        var validator = spec.getProblem().getCheckerConfig().getInputValidator();
        if (validator == null) throw new IllegalArgumentException("Missing input validator");
        var template = validator.getSpj();
        if (Files.exists(directory.resolve("compile.failed"))) {
            Files.copy(
                    directory.resolve("compile.err"),
                    workspace.resolve(err),
                    StandardCopyOption.REPLACE_EXISTING);
            return 8;
        }
        if (!Files.exists(directory)) {
            Files.createDirectories(directory);
            ProcessUtils.execCmd(
                    List.of("sudo", "chmod", "777", directory.toString()),
                    null,
                    workspace.toFile(),
                    5,
                    TimeUnit.SECONDS);
            Path source = directory.resolve(template.getCompile().getSrcName()).normalize();
            if (!source.startsWith(directory))
                throw new IllegalArgumentException("Unsafe validator source path");
            if (validator.getZipFileId() != null) {
                byte[] archive = download(validator.getZipFileId(), 5 * 1024 * 1024);
                if (!HexFormat.of()
                        .formatHex(MessageDigest.getInstance("SHA-256").digest(archive))
                        .equals(spec.getValidatorZipSha256())) {
                    throw new IllegalStateException("Validator ZIP snapshot changed");
                }
                extractZip(archive, directory);
                if (!Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IllegalArgumentException("Validator ZIP lacks template source file");
                }
            } else {
                Files.writeString(source, validator.getSource());
            }
            for (String command : template.getCompile().getCommands()) {
                var compiled =
                        sandbox(
                                directory,
                                substitute(command, spec),
                                Math.min(10000, template.getCompile().getMaxCpuTime()),
                                Math.min(15000, template.getCompile().getMaxRealTime()),
                                template.getCompile().getMaxMemory() * 1024L,
                                null,
                                "/dev/null",
                                "compile.out",
                                "compile.err",
                                16 * 1024 * 1024,
                                false,
                                null,
                                deadline);
                if (compiled == null || compiled.getResult() != 0 || compiled.getExitCode() != 0) {
                    Files.writeString(directory.resolve("compile.failed"), "failed");
                    Files.copy(
                            directory.resolve("compile.err"),
                            workspace.resolve(err),
                            StandardCopyOption.REPLACE_EXISTING);
                    return 8;
                }
            }
        }
        var result =
                sandbox(
                        directory,
                        substitute(template.getRun().getCommand(), spec),
                        2000,
                        4000,
                        256L * 1024 * 1024,
                        template.getRun().getSeccompRule(),
                        workspace.resolve(in).toString(),
                        "validator.out",
                        "validator.err",
                        65536,
                        true,
                        template.getRun().getEnvs(),
                        deadline);
        Files.copy(
                directory.resolve("validator.err"),
                workspace.resolve(err),
                StandardCopyOption.REPLACE_EXISTING);
        if (result == null) return 5;
        return result.getResult() == 0 && result.getExitCode() == 0
                ? 1
                : result.getExitCode() != 0
                        ? 6
                        : SandboxResult.of(result.getResult()).submissionJudgeResult.code;
    }

    private int compare(
            Path workspace,
            RunSpecDTO spec,
            RunCaseInputDTO input,
            String in,
            String out,
            int index,
            Instant deadline)
            throws Exception {
        ProblemCheckerConfigDTO checker = spec.getProblem().getCheckerConfig();
        if (checker != null && checker.getSpj() != null) {
            // Custom checker uses trusted template configuration and the same sandbox limits.
            JudgeTemplateConfigDTO.TemplateConfig custom = checker.getSpj();
            Path checkerWorkspace = workspace.resolve("checker");
            Files.createDirectories(checkerWorkspace);
            ProcessUtils.execCmd(
                    List.of("sudo", "chmod", "777", checkerWorkspace.toString()),
                    null,
                    workspace.toFile(),
                    5,
                    TimeUnit.SECONDS);
            Path checkerSource =
                    checkerWorkspace.resolve(custom.getCompile().getSrcName()).normalize();
            if (!checkerSource.startsWith(checkerWorkspace))
                throw new IllegalArgumentException("Invalid checker path");
            if (!Files.exists(checkerSource)) {
                Files.writeString(checkerSource, checker.getSource());
                for (String command : custom.getCompile().getCommands()) {
                    SandboxResultDTO compiled =
                            sandbox(
                                    checkerWorkspace,
                                    substitute(command, spec),
                                    10000,
                                    15000,
                                    custom.getCompile().getMaxMemory() * 1024L,
                                    null,
                                    "/dev/null",
                                    "checker.compile",
                                    "checker.err",
                                    16 * 1024 * 1024,
                                    false,
                                    null,
                                    deadline);
                    if (compiled == null
                            || compiled.getResult() != 0
                            || compiled.getExitCode() != 0) return 5;
                }
            }
            String expected = index + ".expected";
            Files.writeString(workspace.resolve(expected), input.getExpectedOutput());
            SandboxResultDTO checked =
                    sandbox(
                            checkerWorkspace,
                            substitute(custom.getRun().getCommand(), spec)
                                    + " "
                                    + workspace.resolve(in)
                                    + " "
                                    + workspace.resolve(out)
                                    + " "
                                    + workspace.resolve(expected)
                                    + " checker.report",
                            2000,
                            4000,
                            256L * 1024 * 1024,
                            custom.getRun().getSeccompRule(),
                            "/dev/null",
                            "checker.out",
                            "checker.err",
                            65536,
                            true,
                            custom.getRun().getEnvs(),
                            deadline);
            if (checked == null || checked.getResult() != 0 && checked.getResult() != 4) return 5;
            if (checked.getExitCode() == 0) return 1;
            if (Set.of(1, 3, 4, 7, 8).contains(checked.getExitCode())) return 6;
            if (checked.getExitCode() == 2) return 7;
            return 5;
        }
        if (usesPredefinedChecker(checker)) {
            if (!checkers.isCheckerSourceFilenameExist(checker.getSource()))
                throw new IllegalArgumentException("Unsupported checker");
            if (!checkers.isCheckerExist(checker.getSource()))
                checkers.compilePredefinedChecker(checker.getSource());
            String name = checker.getSource().substring(0, checker.getSource().indexOf('.'));
            Files.writeString(workspace.resolve(index + ".expected"), input.getExpectedOutput());
            SandboxResultDTO checked =
                    sandbox(
                            workspace,
                            PathConfig.CHECKER_DIR
                                    + "/"
                                    + name
                                    + " "
                                    + in
                                    + " "
                                    + out
                                    + " "
                                    + index
                                    + ".expected checker.report",
                            2000,
                            4000,
                            256L * 1024 * 1024,
                            null,
                            "/dev/null",
                            "checker.out",
                            "checker.err",
                            65536,
                            true,
                            null,
                            deadline);
            if (checked == null || checked.getResult() != 0 && checked.getResult() != 4) return 5;
            if (checked.getExitCode() == 0) return 1;
            return checked.getExitCode() == 2
                    ? 7
                    : Set.of(1, 3, 4, 7, 8).contains(checked.getExitCode()) ? 6 : 5;
        }
        throw new IllegalArgumentException("Missing problem checker configuration");
    }

    static boolean usesPredefinedChecker(ProblemCheckerConfigDTO checker) {
        return checker != null && checker.getSpj() == null && checker.getSource() != null;
    }

    private static String substitute(String command, RunSpecDTO spec) {
        return command.replace("{problemTimeLimit}", spec.getProblem().getTimeLimit().toString())
                .replace("{problemMemoryLimit}", spec.getProblem().getMemoryLimit().toString());
    }

    private static SandboxResultDTO sandbox(
            Path cwd,
            String command,
            int cpu,
            int real,
            long memory,
            String rule,
            String input,
            String output,
            String stderr,
            long outputBytes,
            boolean nobody,
            String[] environment,
            Instant deadline)
            throws Exception {
        long remaining = Duration.between(Instant.now(), deadline).toMillis();
        if (remaining <= 0) throw new IllegalStateException("Run execution deadline exceeded");
        real = (int) Math.min(real, remaining);
        cpu = Math.min(cpu, real);
        String[] executable = SPACE.split(command.trim());
        List<String> argv =
                new ArrayList<>(
                        List.of(
                                "sudo",
                                "taskset",
                                "-c",
                                CpuConfig.getCpuSet().iterator().next().toString(),
                                PathConfig.SANDBOX_PATH,
                                "--max_cpu_time=" + cpu,
                                "--max_real_time=" + real,
                                "--max_memory=" + memory,
                                "--max_stack=134217728",
                                "--max_output_size=" + outputBytes,
                                "--exe_path=" + executable[0],
                                "--input_path=" + input,
                                "--output_path=" + output,
                                "--error_path=" + stderr));
        if (rule != null && !rule.isBlank()) argv.add("--seccomp_rules=" + rule);
        if (nobody) {
            argv.add("--uid=65534");
            argv.add("--gid=65534");
        }
        for (int i = 1; i < executable.length; i++) argv.add("--exe_args=" + executable[i]);
        if (environment != null) for (String env : environment) argv.add("--exe_envs=" + env);
        else argv.add("--exe_envs=PATH=" + System.getenv("PATH"));
        ProcessUtils.CommandResult result =
                ProcessUtils.execCmd(
                        argv,
                        null,
                        cwd.toFile(),
                        Math.min(20000, remaining + 250),
                        TimeUnit.MILLISECONDS);
        if (result.exitCode != 0)
            throw new IllegalStateException("Sandbox invocation failed: " + result.stderr);
        return JsonUtils.toObject(result.stdout, SandboxResultDTO.class);
    }

    private static long size(Path path) throws Exception {
        return Files.exists(path, LinkOption.NOFOLLOW_LINKS) ? Files.size(path) : 0;
    }

    public static String prefix(Path path, int bytes) throws Exception {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return "";
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))
            throw new IllegalStateException("Output is not a regular file");
        byte[] data;
        try (var stream = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            data = stream.readNBytes(bytes);
        }
        return StandardCharsets.UTF_8
                .newDecoder()
                .onMalformedInput(java.nio.charset.CodingErrorAction.IGNORE)
                .onUnmappableCharacter(java.nio.charset.CodingErrorAction.IGNORE)
                .decode(java.nio.ByteBuffer.wrap(data))
                .toString();
    }
}
