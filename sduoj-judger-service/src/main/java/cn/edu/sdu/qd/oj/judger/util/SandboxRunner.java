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

import cn.edu.sdu.qd.oj.common.util.JsonUtils;
import cn.edu.sdu.qd.oj.common.util.collection.Lists;
import cn.edu.sdu.qd.oj.judger.config.CpuConfig;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import lombok.extern.slf4j.Slf4j;

import java.io.File;
import java.util.List;

/**
 * Run sandbox with CPU affinity
 *
 * @author zhangt2333
 * @author jeshrz
 */
@Slf4j
public class SandboxRunner {

    private static final String SANDBOX_PATH = "/usr/bin/sandbox";

    private static final long TIMEOUT_IN_SECONDS = 5 * 60L; // 5 minutes

    public static SandboxResultDTO run(String cwd, Argument args) throws SystemErrorException {
        return run(CpuConfig.getCpuSet().iterator().next(), cwd, args);
    }

    public static SandboxResultDTO run(int coreNo, String cwd, Argument args) throws SystemErrorException {
        List<String> command = Lists.newArrayList(
                "sudo",
                "taskset",
                "-c",
                String.valueOf(coreNo),
                SANDBOX_PATH
        );
        command.addAll(args.getFormatArgs());

        ProcessUtils.CommandResult result = ShellUtils.execCmd(command, new File(cwd), TIMEOUT_IN_SECONDS);
        log.info("\nsandbox output: {}", result.stdout);
        if (result.exitCode != 0) {
            throw new SystemErrorException(String.format("Sandbox exits abnormally: %d", result.exitCode));
        }
        return JsonUtils.toObject(result.stdout, SandboxResultDTO.class);
    }
}
