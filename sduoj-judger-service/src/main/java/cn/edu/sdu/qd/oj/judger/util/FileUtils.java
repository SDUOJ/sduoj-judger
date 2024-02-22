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

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public class FileUtils {

    // buffer size used for reading and writing
    private static final int BUFFER_SIZE = 8192;

    /**
     * Internal byte array buffer.
     */
    private static final ThreadLocal<char[]> CHAR_BUFFER = ThreadLocal.withInitial(() -> new char[BUFFER_SIZE]);

    public static void createDir(String path) throws SystemErrorException {
        File file = new File(path);
        if (!file.exists() && !file.mkdirs()) {
            throw new SystemErrorException(String.format("create dir \"%s\" failed", path));
        }
    }

    public static void writeFile(String path, String content) throws SystemErrorException {
        try {
            org.apache.commons.io.FileUtils.writeStringToFile(new File(path), content, StandardCharsets.UTF_8);
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

    /**
     * Reads the first N characters from a file at the given path.
     *
     * @param path the path to the file
     * @param numChars the number of characters to read
     * @return a string containing the first N characters of the file
     */
    public static String readFirstNChars(Path path, int numChars) throws SystemErrorException {
        if (numChars <= 0) {
            throw new IllegalArgumentException("numChars must be greater than 0");
        }
        StringBuilder result = new StringBuilder(numChars);
        try (BufferedReader reader = Files.newBufferedReader(path)) {
            int count = 0;
            char[] buffer = CHAR_BUFFER.get();
            int n;
            while (count < numChars && (n = reader.read(buffer)) != -1) {
                n = Math.min(numChars - count, n);
                result.append(buffer, 0, n);
                count += n;
            }
        } catch (IOException e) {
            throw new SystemErrorException(e);
        }
        return result.toString();
    }

    public static String readFirstNChars(String path, int numChars) throws SystemErrorException {
        return readFirstNChars(Path.of(path), numChars);
    }

}
