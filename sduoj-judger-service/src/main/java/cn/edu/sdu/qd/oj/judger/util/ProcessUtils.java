package cn.edu.sdu.qd.oj.judger.util;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.IOUtils;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;

@Slf4j
public class ProcessUtils {

    public static void chmod(String path, String mode) throws SystemErrorException {
        cmdOnRootPath("sudo", "chmod", mode, path);
    }

    public static void chown(String path, String own) throws SystemErrorException {
        cmdOnRootPath("sudo", "chown", own, path);
    }

    /**
     * 运行一个外部命令，返回状态.若超过指定的超时时间，抛出TimeoutException
     */
    public static ProcessStatus cmd(String cwd, final String... commands) throws SystemErrorException {
        Process process = null;
        Worker worker = null;
        try {
            process = new ProcessBuilder("/bin/sh", "-c", String.join(" ", commands))
                    .directory((cwd == null || cwd.equals("")) ? null : new File(cwd))
                    .redirectErrorStream(true)
                    .start();

            worker = new Worker(process);
            worker.start();
            ProcessStatus ps = worker.getProcessStatus();
            worker.join(120000);    /* 最多运行 120s */
            if (ps.exitCode == ProcessStatus.CODE_STARTED) {
                // not finished
                worker.interrupt();
                throw new SystemErrorException("Timeout");
            } else {
                return ps;
            }
        } catch (InterruptedException | IOException e) {
            // canceled by other thread.
            worker.interrupt();
            throw new SystemErrorException("Canceled by other thread");
        } finally {
            process.destroy();
        }
    }

    public static ProcessStatus cmdOnRootPath(final String... commands) throws SystemErrorException {
        return ProcessUtils.cmd(null, commands);
    }

    private static class Worker extends Thread {
        private final Process process;
        private final ProcessStatus ps;

        private Worker(Process process) {
            this.process = process;
            this.ps = new ProcessStatus();
        }

        public void run() {
            try {
                InputStream is = process.getInputStream();
                try {
                    ps.output = IOUtils.toString(is);
                } catch (IOException ignore) {
                }
                ps.exitCode = process.waitFor();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        public ProcessStatus getProcessStatus() {
            return this.ps;
        }
    }

    public static class ProcessStatus {
        public static final int CODE_STARTED = -257;
        public volatile int exitCode;
        public volatile String output;
    }
}
