package cn.edu.sdu.qd.oj.judger.util;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import org.apache.commons.io.FileUtils;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

public class ShellUtils {
    public static void createDir(String path) throws SystemErrorException {
        File file = new File(path);
        if (!file.exists() && !file.mkdirs()) {
            throw new SystemErrorException(String.format("create dir \"%s\" failed", path));
        }
    }

    public static void writeFile(String path, String content) throws SystemErrorException {
        try {
            FileUtils.writeStringToFile(new File(path), content);
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not write to file \"%s\": %s", path, e));
        }
    }

    public static String readFile(String path) throws SystemErrorException {
        try {
            return FileUtils.readFileToString(new File(path), String.valueOf(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new SystemErrorException(e);
        }
    }


    public static void chmod(String path, String mode) throws SystemErrorException {
        cmd(String.format("chmod %s %s", mode, path));
    }

    public static void chown(String path, String own) throws SystemErrorException {
        cmd(String.format("chown %s %s", own, path));
    }

    public static void cmd(String cmd) throws SystemErrorException {
        try {
            if (Runtime.getRuntime().exec(cmd).waitFor() != 0) {
                throw new Exception();
            }
        } catch (Exception e) {
            throw new SystemErrorException(String.format("exec \"%s\" failed", cmd));
        }
    }
}
