package cn.edu.sdu.qd.oj.judger.util;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import com.alibaba.fastjson.JSON;
import lombok.extern.slf4j.Slf4j;

import java.util.ArrayList;
import java.util.List;

@Slf4j
public class SandboxRunner {

    private static final String SANDBOX_PATH = "/usr/bin/sandbox";

    public static SandboxResultDTO run(int coreNo, String cwd, Argument... args) throws SystemErrorException {
        List<String> commandList = new ArrayList<>();

        commandList.add("sudo");
        commandList.add("taskset");
        commandList.add("-c");
        commandList.add(String.valueOf(coreNo));
        commandList.add(SANDBOX_PATH);

        for (Argument arg : args) {
            if (arg == null || arg.value == null) {
                continue;
            }
            if (arg.key.clz == String.class) {
                commandList.add(String.format("--%s=\"%s\"", arg.key, arg.value));
            } else if (arg.key.clz == String[].class) {
                String[] values = (String[]) arg.key.clz.cast(arg.value);
                for (String value : values) {
                    commandList.add(String.format("--%s=\"%s\"", arg.key, value));
                }
            } else {
                commandList.add(String.format("--%s=%s", arg.key, arg.value));
            }
        }

        log.info("sandbox {}", String.join(" ", commandList));

        ProcessUtils.ProcessStatus processStatus = ProcessUtils.cmd(cwd, commandList.toArray(new String[0]));
        if (processStatus.exitCode != 0) {
            throw new SystemErrorException(String.format("Sandbox exits abnormally: %d", processStatus.exitCode));
        }
        log.info("output {}", processStatus.output);
        return JSON.parseObject(processStatus.output, SandboxResultDTO.class);
    }
}
