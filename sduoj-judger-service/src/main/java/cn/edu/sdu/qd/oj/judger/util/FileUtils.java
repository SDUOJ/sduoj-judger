package cn.edu.sdu.qd.oj.judger.util;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

public class FileUtils {
    public static void createDir(String path) throws SystemErrorException {
        File file = new File(path);
        if (!file.exists() && !file.mkdirs()) {
            throw new SystemErrorException(String.format("create dir \"%s\" failed", path));
        }
    }

    public static void writeFile(String path, String content) throws SystemErrorException {
        try {
            org.apache.commons.io.FileUtils.writeStringToFile(new File(path), content);
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not write to file \"%s\": %s", path, e));
        }
    }

    public static void writeFile(String path, byte[] content) throws SystemErrorException {
        try {
            org.apache.commons.io.FileUtils.writeByteArrayToFile(new File(path), content);
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not write to file \"%s\": %s", path, e));
        }
    }

    public static String readFile(String path) throws SystemErrorException {
        try {
            return org.apache.commons.io.FileUtils.readFileToString(new File(path), String.valueOf(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new SystemErrorException(e);
        }
    }
}