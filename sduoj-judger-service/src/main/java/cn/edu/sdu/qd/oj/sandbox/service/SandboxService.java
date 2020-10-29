package cn.edu.sdu.qd.oj.sandbox.service;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import com.alibaba.fastjson.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.Closeable;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.text.MessageFormat;
import java.util.ArrayList;
import java.util.List;

@Slf4j
@Service
public class SandboxService {

    private static final String SANDBOX_PATH = "/usr/bin/sandbox";

    public SandboxResultDTO run(int coreNo, Argument... args) throws SystemErrorException {
        List<String> commandList = new ArrayList<>();

        commandList.add("taskset");
        commandList.add("-c");
        commandList.add(String.valueOf(coreNo));
        commandList.add(SANDBOX_PATH);

        for (Argument arg : args) {
            if (arg.value == null) {
                continue;
            }
            if (arg.key.clz == String.class) {
                commandList.add(MessageFormat.format("--{}=\"{}\"", arg.key, arg.key.clz.cast(arg.value)));
            } else if (arg.key.clz == String[].class) {
                String[] values = (String[]) arg.key.clz.cast(arg.value);
                for (String value : values) {
                    commandList.add(MessageFormat.format("--{}=\"{}\"", arg.key, value));
                }
            } else {
                commandList.add(MessageFormat.format("--{}={}", arg.key, arg.key.clz.cast(arg.value)));
            }
        }

        log.info("sandbox {}", String.join(" ", commandList));

        ProcessUtils.ProcessStatus processStatus = ProcessUtils.cmd((String[]) commandList.toArray());
        if (processStatus.exitCode != 0) {
            throw new SystemErrorException(String.format("Sandbox exits abnormally: %d", processStatus.exitCode));
        }
        return JSON.parseObject(processStatus.output, SandboxResultDTO.class);
    }
}
