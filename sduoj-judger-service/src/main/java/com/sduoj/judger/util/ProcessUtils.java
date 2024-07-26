/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.util;

import lombok.extern.slf4j.Slf4j;

import javax.annotation.Nullable;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * Some utils for running command in Terminal.
 *
 * @author zhangt2333
 * @see ShellUtils
 */
@Slf4j
public class ProcessUtils {

    protected ProcessUtils() {
    }

    /**
     * 当前线程会同步等待对应执行命令的进程结束
     */
    protected static CommandResult execCmd(final List<String> commands,
                                           @Nullable final Map<String, String> environment,
                                           @Nullable final File workingDirectory,
                                           final long timeout,
                                           final TimeUnit unit) {
        // construct arguments
        ProcessBuilder builder = new ProcessBuilder();
        builder.command(commands);
        if (environment != null) {
            Map<String, String> env = builder.environment();
            env.clear();
            env.putAll(environment);
        }
        if (workingDirectory != null) {
            builder.directory(workingDirectory);
        }
        // run
        Process process = null;
        int exitCode = 1;
        String stdout = null;
        String stderr = null;
        try {
            process = builder.start();
            if (timeout == 0) {
                process.waitFor();
            } else {
                process.waitFor(timeout, unit);
            }
            if (!process.isAlive()) {
                exitCode = process.exitValue();
            }
            stdout = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            stderr = new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
        } catch (Exception e) {
            log.error("", e);
        } finally {
            if (process != null) {
                process.destroyForcibly();
            }
        }
        return new CommandResult(exitCode, stdout, stderr);
    }

    public static class CommandResult {
        public static final int PROCESS_NOT_FINISHED = -257;

        public final int exitCode;
        public final String stdout;
        public final String stderr;

        CommandResult(int exitCode, String stdout, String stderr) {
            this.exitCode = exitCode;
            this.stdout = stdout == null ? "" : stdout;
            this.stderr = stderr == null ? "" : stderr;
        }

        @Override
        public String toString() {
            return "CommandResult{" +
                    "exitCode=" + exitCode +
                    ", stdout='" + stdout + '\'' +
                    ", stderr='" + stderr + '\'' +
                    '}';
        }
    }
}
