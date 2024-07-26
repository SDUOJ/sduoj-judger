package com.sduoj.judger.util;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.Assert.assertEquals;

public class FileUtilsTest {

    private Path tempFile;

    @Before
    public void setUp() throws IOException {
        tempFile = Files.createTempFile("test-file", ".txt");
    }

    @After
    public void tearDown() throws IOException {
        Files.deleteIfExists(tempFile);
    }

    private void writeToFile(String content) throws IOException {
        try (BufferedWriter writer = Files.newBufferedWriter(tempFile)) {
            writer.write(content);
        }
    }

    @Test
    public void testReadNCharsMoreThanAvailable() throws Exception {
        String content = "Hello, World!";
        writeToFile(content);
        String result = FileUtils.readFirstNChars(tempFile.toString(), 20);
        assertEquals("Should read all available characters", content, result);
    }

    @Test
    public void testReadNCharsExactlyAvailable() throws Exception {
        String content = "Hello, World!";
        writeToFile(content);
        String result = FileUtils.readFirstNChars(tempFile.toString(), content.length());
        assertEquals("Should read exactly the number of available characters", content, result);
    }

    @Test
    public void testReadNCharsLessThanAvailable() throws Exception {
        String content = "Hello, World!";
        writeToFile(content);
        String result = FileUtils.readFirstNChars(tempFile.toString(), 5);
        assertEquals("Should read the first N characters", "Hello", result);
    }

    @Test
    public void testReadNCharsFromEmptyFile() throws Exception {
        writeToFile(""); // Empty file
        String result = FileUtils.readFirstNChars(tempFile.toString(), 10);
        assertEquals("Should return an empty string for an empty file", "", result);
    }

    @Test(expected = IllegalArgumentException.class)
    public void testReadNCharsInvalidNumChars() throws Exception {
        FileUtils.readFirstNChars(tempFile.toString(), -1);
        // No need for an assertion here, as the test will fail if the expected exception is not thrown.
    }

}
