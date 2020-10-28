package cn.edu.sdu.qd.oj.sandbox.service;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
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

    public SandboxResultDTO run(int cpuId, Argument... args) throws SystemErrorException {
        List<String> commandList = new ArrayList<>();

        commandList.add(MessageFormat.format("taskset -c {}", cpuId));
        commandList.add(SANDBOX_PATH);

        for (Argument arg : args) {
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
        String command = String.join(" ", commandList);
        log.info("sandbox {}", command);

        Process process = null;
        BufferedReader bufIn = null;
        StringBuilder result = new StringBuilder();
        try {
            // 构建子进程运行沙箱
            process = Runtime.getRuntime().exec(command);
            if (process.waitFor() != 0) {
                throw new SystemErrorException("Sandbox exits abnormally");
            }
            // correct
            // 收集沙箱的输出
            bufIn = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
            String line;
            while ((line = bufIn.readLine()) != null) {
                result.append(line);
            }
        } catch (IOException | InterruptedException e) {
            // nothing
        } finally {
            closeStream(bufIn);
            if (process != null) {
                process.destroy();
            }
        }
        return JSON.parseObject(result.toString(), SandboxResultDTO.class);
    }

    private void closeStream(Closeable stream) {
        try {
            if (stream != null) {
                stream.close();
            }
        } catch (Exception e) {
            // nothing
        }
    }
}
