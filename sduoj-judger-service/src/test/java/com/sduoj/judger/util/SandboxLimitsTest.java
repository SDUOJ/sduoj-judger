package com.sduoj.judger.util;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.file.Files;
import java.nio.file.Path;

public class SandboxLimitsTest {
    private static final long GiB = 1024L * 1024 * 1024;

    @Test
    public void zeroJavaLimitsBecomeAnExplicitPhysicalSafetyCapNotItsHeapSize() {
        assertEquals(GiB, SandboxLimits.compileBytes(0, GiB));
        assertEquals(GiB, SandboxLimits.runtimeBytes(65536, 0, GiB));
        assertEquals(2 * GiB, SandboxLimits.runtimeBytes(65536, 0, 2 * GiB));
        assertEquals(GiB, SandboxLimits.runRuntimeBytes(65536, 0, GiB));
    }

    @Test
    public void finiteTemplatesAndExistingRunCeilingRemainUnchanged() {
        assertEquals(512L * 1024 * 1024, SandboxLimits.compileBytes(524288, GiB));
        assertEquals(256L * 1024 * 1024, SandboxLimits.runtimeBytes(131072, 2, GiB));
        assertEquals(512L * 1024 * 1024, SandboxLimits.runRuntimeBytes(1048576, 2, GiB));
    }

    @Test
    public void invalidAndOverflowingLimitsFailClosed() {
        assertThrows(IllegalArgumentException.class, () -> SandboxLimits.compileBytes(-1, GiB));
        assertThrows(IllegalArgumentException.class, () -> SandboxLimits.compileBytes(0, 0));
        assertThrows(IllegalArgumentException.class, () -> SandboxLimits.runtimeBytes(1, -1, GiB));
        assertThrows(IllegalArgumentException.class, () -> SandboxLimits.runtimeBytes(0, 0, GiB));
        assertThrows(IllegalArgumentException.class, () -> SandboxLimits.compileBytes(0, 9 * GiB));
        assertThrows(ArithmeticException.class, () -> SandboxLimits.runtimeBytes(Long.MAX_VALUE, 2, GiB));
    }

    @Test
    public void cgroupRootNeverFallsBackToHostHierarchyOrOrdinaryDirectories() throws Exception {
        assertThrows(IllegalStateException.class, () -> SandboxLimits.cgroupRoot(null));
        assertThrows(IllegalStateException.class, () -> SandboxLimits.cgroupRoot("/"));
        assertThrows(IllegalStateException.class, () -> SandboxLimits.cgroupRoot("/sys/fs/cgroup"));
        assertThrows(IllegalStateException.class, () -> SandboxLimits.cgroupRoot("../cgroup"));
        Path plain = Files.createTempDirectory("not-a-cgroup");
        try {
            assertThrows(IllegalStateException.class, () -> SandboxLimits.cgroupRoot(plain.toString()));
        } finally {
            Files.delete(plain);
        }
    }
}
