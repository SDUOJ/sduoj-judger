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
        createDir(new File(path));
    }

    public static void createDir(File dir) throws SystemErrorException {
        if (!dir.exists() && !dir.mkdirs()) {
            throw new SystemErrorException(String.format("create dir \"%s\" failed", dir));
        }
    }

    public static void writeFile(Path path, String content) throws SystemErrorException {
        writeFile(path, content.getBytes(StandardCharsets.UTF_8));
    }

    public static void writeFile(String path, String content) throws SystemErrorException {
        writeFile(Path.of(path), content);
    }

    public static void writeFile(Path path, byte[] content) throws SystemErrorException {
        try {
            createDir(path.getParent().toFile());
            Files.write(path, content);
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Can not write to file \"%s\": %s", path, e));
        }
    }

    public static void writeFile(String path, byte[] content) throws SystemErrorException {
        writeFile(Path.of(path), content);
    }

    public static String readFile(Path path) throws SystemErrorException {
        try {
            return Files.readString(path);
        } catch (IOException e) {
            throw new SystemErrorException(e);
        }
    }

    public static String readFile(String path) throws SystemErrorException {
        return readFile(Path.of(path));
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
