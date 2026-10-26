package com.sduoj.judger.util;

import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.io.IOException;

/** Translate legacy zero/unlimited templates into explicit host safety limits.
 * These caps bound physical sandbox memory; they do not change JVM heap flags.
 */
public final class SandboxLimits {
    public static final long DEFAULT_FALLBACK_BYTES = 1024L * 1024 * 1024;
    private static final long MAX_FALLBACK_BYTES = 8L * 1024 * 1024 * 1024;
    private SandboxLimits() {}

    public static long compileBytes(long templateKiB, long fallbackBytes) {
        requireFallback(fallbackBytes);
        if (templateKiB < 0) throw new IllegalArgumentException("Negative compiler memory");
        return templateKiB == 0 ? fallbackBytes : Math.multiplyExact(templateKiB, 1024L);
    }

    public static long runtimeBytes(long problemKiB, long factor, long fallbackBytes) {
        requireFallback(fallbackBytes);
        if (problemKiB <= 0 || factor < 0)
            throw new IllegalArgumentException("Invalid runtime memory");
        return factor == 0 ? fallbackBytes
                : Math.multiplyExact(Math.multiplyExact(problemKiB, factor), 1024L);
    }

    public static long runRuntimeBytes(long problemKiB, long factor, long fallbackBytes) {
        long bytes = runtimeBytes(problemKiB, factor, fallbackBytes);
        // Keep the existing 512 MiB Run cap for finite template multipliers.
        // The legacy zero multiplier was unlimited, not a 0-byte allocation.
        return factor == 0 ? bytes : Math.min(512L * 1024 * 1024, bytes);
    }

    private static void requireFallback(long bytes) {
        if (bytes < 32L * 1024 * 1024 || bytes > MAX_FALLBACK_BYTES)
            throw new IllegalArgumentException("Memory fallback must be 32 MiB..8 GiB");
    }

    public static String cgroupRoot() {
        return cgroupRoot(System.getenv("SDUOJ_CGROUP_ROOT"));
    }

    static String cgroupRoot(String value) {
        if (value == null || value.isBlank())
            throw new IllegalStateException("Trusted judge entrypoint must delegate a run cgroup");
        Path path = Path.of(value);
        if (!path.isAbsolute() || !path.normalize().equals(path)
                || path.getNameCount() < 2 || path.equals(Path.of("/sys/fs/cgroup"))
                || !Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS))
            throw new IllegalStateException("Invalid dedicated run cgroup");
        try {
            if (!"cgroup2".equals(Files.getFileStore(path).type())
                    || !path.toRealPath().equals(path)
                    || !Integer.valueOf(0).equals(Files.getAttribute(path, "unix:uid",
                            LinkOption.NOFOLLOW_LINKS))
                    || !Files.isRegularFile(path.resolve("cgroup.procs"))
                    || !Files.readString(path.resolve("cgroup.procs")).isBlank()
                    || !Files.readString(path.resolve("cgroup.subtree_control")).contains("memory")
                    || !Files.readString(path.resolve("cgroup.subtree_control")).contains("pids"))
                throw new IllegalStateException("Run cgroup must be root-owned, empty and delegated");
        } catch (IOException failure) {
            throw new IllegalStateException("Cannot verify dedicated run cgroup", failure);
        }
        return path.toString();
    }
}
