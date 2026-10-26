package com.sduoj.judger.util;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Comparator;

/** One checker invocation sees only its sealed artifact and this case's copies.
 * The submitted program never uses this directory. Report is initially absent,
 * so the native argument binder cannot mount it read-only before checker writes.
 */
public final class CheckerWorkspace implements AutoCloseable {
    private final Path root;
    private CheckerWorkspace(Path root) { this.root = root; }
    public Path root() { return root; }
    public Path input() { return root.resolve("case-input"); }
    public Path output() { return root.resolve("case-output"); }
    public Path answer() { return root.resolve("case-answer"); }
    public Path report() { return root.resolve("case-report"); }
    public String arguments() {
        return " " + input() + " " + output() + " " + answer() + " " + report();
    }

    public static CheckerWorkspace create(Path task, Path artifacts, Path input,
            Path output, Path answer) throws IOException {
        Path root = Files.createTempDirectory(task, "checker-case-",
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwxr-xr-x")));
        CheckerWorkspace workspace = new CheckerWorkspace(root);
        try {
            copyArtifacts(artifacts, root);
            copyFile(input, workspace.input(), 5L * 1024 * 1024);
            copyFile(output, workspace.output(), 65536);
            copyFile(answer, workspace.answer(), 5L * 1024 * 1024);
            // Only this invocation may write its cwd. Existing immutable inputs
            // cannot be modified; replacing one affects no other scene/case.
            Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwxrwxrwx"));
            return workspace;
        } catch (IOException | RuntimeException error) {
            WorkspaceFiles.delete(root);
            throw error;
        }
    }

    private static void copyArtifacts(Path artifacts, Path destination) throws IOException {
        if (!Files.isDirectory(artifacts, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Checker artifacts must use a real directory");
        int count = 0;
        long bytes = 0;
        try (var paths = Files.walk(artifacts)) {
            for (Path path : paths.sorted(Comparator.comparingInt(Path::getNameCount)).toList()) {
                if (path.equals(artifacts)) continue;
                if (++count > 1024) throw new IOException("Too many checker artifacts");
                Path relative = artifacts.relativize(path);
                if (relative.getNameCount() > 32) throw new IOException("Checker artifact too deep");
                if (relative.toString().matches("case-(input|output|answer|report)"))
                    throw new IOException("Reserved checker case path");
                BasicFileAttributes info = Files.readAttributes(path, BasicFileAttributes.class,
                        LinkOption.NOFOLLOW_LINKS);
                Path target = destination.resolve(relative);
                if (info.isDirectory()) {
                    Files.createDirectory(target, PosixFilePermissions.asFileAttribute(
                            PosixFilePermissions.fromString("rwxr-xr-x")));
                } else if (info.isRegularFile()) {
                    bytes = Math.addExact(bytes, info.size());
                    if (bytes > 64L * 1024 * 1024) throw new IOException("Checker artifacts too large");
                    copyFile(path, target, 64L * 1024 * 1024);
                    Files.setPosixFilePermissions(target, PosixFilePermissions.fromString("r-xr-xr-x"));
                } else {
                    throw new IOException("Checker artifact is a link or special file");
                }
            }
        }
    }

    private static void copyFile(Path source, Path destination, long limit) throws IOException {
        BasicFileAttributes info = Files.readAttributes(source, BasicFileAttributes.class,
                LinkOption.NOFOLLOW_LINKS);
        if (!info.isRegularFile() || info.size() > limit)
            throw new IOException("Checker input is not a bounded regular file");
        // No COPY_ATTRIBUTES: create a fresh operator-owned inode, not an alias.
        Files.copy(source, destination, LinkOption.NOFOLLOW_LINKS);
        if (!Files.isRegularFile(destination, LinkOption.NOFOLLOW_LINKS)
                || Files.size(destination) > limit)
            throw new IOException("Checker input changed while copying");
        Files.setPosixFilePermissions(destination, PosixFilePermissions.fromString("r--r--r--"));
    }

    @Override
    public void close() throws IOException { WorkspaceFiles.delete(root); }
}
