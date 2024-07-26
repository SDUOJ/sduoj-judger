/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.util;


import lombok.extern.slf4j.Slf4j;

import javax.annotation.Nullable;
import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * Some utils for running command in *nix Terminal.
 * You can overwrite the methods on demand.
 *
 * @author zhangt2333
 */
@Slf4j
public final class ShellUtils extends ProcessUtils {

    private ShellUtils() {
    }

    /* -------------------------- Utils --------------------------------- */

    public static void chmod(String path, String mode) {
        CommandResult result = ShellUtils.execCmd("sudo", "chmod", "-R", mode, path);
        if (result.exitCode != 0) {
            throw new RuntimeException("Run chmod error: " + result);
        }
    }

    public static void chown(String path, String own) {
        CommandResult result = ShellUtils.execCmd("sudo", "chown", own, path);
        if (result.exitCode != 0) {
            throw new RuntimeException("Run chown error: " + result);
        }
    }

    public static boolean unzip(String zipFilePath, String targetDirPath) {
        CommandResult result = ShellUtils.execCmd("sudo", "unzip",
                "-o", "-q", "-d", targetDirPath, zipFilePath);
        if (result.exitCode != 0) {
            log.warn("unzip error: {}", result);
            return false;
        }
        return true;
    }

    public static void deleteWorkspaceDir(String path) {
        if (path.startsWith("/workspace/")) {
            ShellUtils.execCmd("sudo", "rm", "-rf", path);
        } else {
            log.warn("deleteDir {}", path);
        }
    }

    /* --------------------------- runner ----------------------------------- */

    public static CommandResult execCmd(final String... commands) {
        List<String> finalCommand = new ArrayList<>(commands.length);
        Collections.addAll(finalCommand, commands);
        return ShellUtils.execCmd(finalCommand, null, null, 0, TimeUnit.SECONDS);
    }

    public static CommandResult execCmd(final List<String> commands) {
        return ShellUtils.execCmd(commands, null, null, 0, TimeUnit.SECONDS);
    }

    public static CommandResult execCmd(final List<String> commands,
                                        final long timeoutInSeconds) {
        return ShellUtils.execCmd(commands, null, null, timeoutInSeconds, TimeUnit.SECONDS);
    }

    public static CommandResult execCmd(final List<String> commands,
                                        @Nullable final File workingDirectory,
                                        final long timeoutInSeconds) {
        return ShellUtils.execCmd(commands, null, workingDirectory, timeoutInSeconds, TimeUnit.SECONDS);
    }

    public static CommandResult execCmd(final List<String> commands,
                                        @Nullable final Map<String, String> environment,
                                        @Nullable final File workingDirectory,
                                        final long timeoutInSeconds) {
        return ShellUtils.execCmd(commands, environment, workingDirectory, timeoutInSeconds, TimeUnit.SECONDS);
    }

    /**
     * 当前线程会同步等待对应执行命令的进程结束
     */
    public static CommandResult execCmd(final List<String> commands,
                                        @Nullable final Map<String, String> environment,
                                        @Nullable final File workingDirectory,
                                        final long timeout,
                                        final TimeUnit unit) {
        String command = String.join(" ", commands);
        log.info("Run command: {}", command);

        List<String> finalCommands = new ArrayList<>(3);
        Collections.addAll(finalCommands, "/bin/sh", "-c", command);
        return ProcessUtils.execCmd(finalCommands, environment, workingDirectory, timeout, unit);
    }
}
