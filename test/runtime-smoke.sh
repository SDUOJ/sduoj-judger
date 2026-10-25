#!/usr/bin/env bash
# Run inside the final judge image on its native architecture.
set -euo pipefail
expected_arch=${1:?expected native architecture is required}
test "$(uname -m)" = "$expected_arch"
java -version
sandbox --help | grep -q -- '--error_path'
workspace=$(mktemp -d /tmp/sduoj-runtime-smoke.XXXXXX)
trap 'rm -rf "$workspace"' EXIT
chmod 755 "$workspace"
cat > "$workspace/main.cpp" <<'CPP'
#include <iostream>
#include <fcntl.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>
int main(int argc, char **argv) {
    long first, second;
    if (!(std::cin >> first >> second)) return 2;
    std::cout << first + second << "\n";
    std::cerr << "diagnostic\n";
    if (argc == 3) {
        if (argv[1][0] == 'n') syscall(SYS_socket, AF_INET, SOCK_STREAM, 0);
        else if (argv[1][0] == 'p') syscall(SYS_clone, SIGCHLD, 0, 0, 0, 0);
        else if (argv[1][0] == 'w') syscall(SYS_openat, AT_FDCWD, argv[2], O_WRONLY | O_CREAT, 0600);
        return 77;
    }
}
CPP
/opt/gcc/13.2.0/bin/g++ -std=c++17 -O2 -static "$workspace/main.cpp" -o "$workspace/main"
printf '17 25\n' > "$workspace/input"
sandbox --max_cpu_time=1000 --max_real_time=3000 --max_memory=268435456 \
    --max_stack=134217728 --max_process_number=128 --max_output_size=65536 \
    --max_io_input_size=65536 --io_mode=memfd --isolate_fs=1 --work_readonly=1 \
    --exe_path="$workspace/main" \
    --input_path="$workspace/input" --output_path="$workspace/output" \
    --error_path="$workspace/error" --seccomp_rules=c_cpp \
    --uid=65534 --gid=65534 > "$workspace/result.json"
python3 - "$workspace" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
result = json.loads((root / 'result.json').read_text())
required = {'cpu_time', 'real_time', 'memory', 'signal', 'exit_code', 'error', 'result'}
assert required <= set(result), result
assert result['result'] == result['exit_code'] == result['error'] == result['signal'] == 0, result
assert (root / 'output').read_text() == '42\n'
assert (root / 'error').read_text() == 'diagnostic\n'
print(json.dumps({'native_architecture': __import__('platform').machine(), 'sandbox': result,
                  'stdout_separate': True, 'stderr_separate': True, 'c_cpp_policy': True}))
PY
mkdir "$workspace/writable"
chmod 777 "$workspace/writable"
for probe in network process write; do
    target="$workspace/writable/$probe.created"
    sandbox --max_cpu_time=1000 --max_real_time=3000 --max_memory=268435456 \
        --max_stack=134217728 --max_process_number=128 --max_output_size=65536 \
        --max_io_input_size=65536 --io_mode=memfd --isolate_fs=1 --work_readonly=1 \
        --exe_path="$workspace/main" \
        --exe_args="$probe" --exe_args="$target" \
        --input_path="$workspace/input" --output_path="$workspace/$probe.out" \
        --error_path="$workspace/$probe.err" --seccomp_rules=c_cpp \
        --uid=65534 --gid=65534 > "$workspace/$probe.json"
    python3 - "$workspace" "$probe" "$target" <<'PY'
import json
from pathlib import Path
import signal
import sys
root, probe, target = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
result = json.loads((root / (probe + '.json')).read_text())
required = {'cpu_time', 'real_time', 'memory', 'signal', 'exit_code', 'error', 'result'}
assert required <= set(result), result
assert result['signal'] == signal.SIGSYS and result['result'] == 4 and result['error'] == 0, result
# Matching output proves the program reached the probe after ordinary C++ startup.
assert (root / (probe + '.out')).read_text() == '42\n'
assert (root / (probe + '.err')).read_text() == 'diagnostic\n'
assert not target.exists(), target
print(json.dumps({'denied_probe': probe, 'sandbox': result}))
PY
done

# Exercise the helper classes shipped in this exact image, including their Linux ownership rules.
mkdir "$workspace/helper-classes"
(
    cd "$workspace/helper-classes"
    jar xf /app/sduoj-judger.jar \
        BOOT-INF/classes/com/sduoj/judger/util/HelperCompilation.class \
        'BOOT-INF/classes/com/sduoj/judger/util/HelperCompilation$CompilerProcess.class' \
        BOOT-INF/classes/com/sduoj/judger/util/WorkspaceFiles.class
)
test -s "$workspace/helper-classes/BOOT-INF/classes/com/sduoj/judger/util/HelperCompilation.class"
cat > "$workspace/HelperRuntimeSmoke.java" <<'JAVA'
import com.sduoj.judger.util.HelperCompilation;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import java.util.concurrent.TimeUnit;

class HelperRuntimeSmoke {
    static Path directory(Path path, String permissions) throws Exception {
        return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString(permissions)));
    }
    static String sandbox(Path cwd, int uid, String executable, List<String> arguments,
            Path input, Path output, Path error, int outputBytes, boolean restricted) throws Exception {
        var command = new ArrayList<>(List.of("/usr/bin/sandbox", "--max_cpu_time=10000",
                "--max_real_time=15000", "--max_memory=536870912", "--max_stack=134217728",
                "--max_process_number=128", "--max_output_size=" + outputBytes,
                "--max_io_input_size=67108864", "--io_mode=memfd", "--isolate_fs=1",
                "--work_readonly=" + (restricted ? "1" : "0"), "--uid=" + uid, "--gid=" + uid,
                "--exe_envs=PATH=" + System.getenv("PATH"),
                "--exe_path=" + executable, "--input_path=" + input,
                "--output_path=" + output, "--error_path=" + error));
        for (String argument : arguments) command.add("--exe_args=" + argument);
        if (restricted) command.add("--seccomp_rules=c_cpp");
        var process = new ProcessBuilder(command).directory(cwd.toFile())
                .redirectErrorStream(true).start();
        if (!process.waitFor(20, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new AssertionError("Helper runtime sandbox timed out");
        }
        String result = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        if (process.exitValue() != 0) throw new AssertionError(result);
        return result;
    }
    static void successful(String result) {
        for (String field : List.of("result", "exit_code", "error", "signal")) {
            if (!result.matches("(?s).*\"" + field + "\"\\s*:\\s*0\\s*[,}].*")) {
                throw new AssertionError(result);
            }
        }
    }
    public static void main(String[] args) throws Exception {
        Path base = directory(Path.of(args[0]).resolve("helpers"), "rwxr-xr-x");
        Path task = directory(base.resolve("first"), "rwx--x--x");
        Path other = directory(base.resolve("second"), "rwx--x--x");
        Path sealed = directory(task.resolve("sealed"), "rwxr-xr-x");
        try (var helper = HelperCompilation.create(task);
                var second = HelperCompilation.create(other)) {
            if (helper.uid() <= 0 || helper.uid() == 65534 || helper.uid() == second.uid()) {
                throw new AssertionError("Helper identities are not exclusive non-root users");
            }
            directory(helper.build().resolve("src"), "rwxr-xr-x");
            Files.writeString(helper.build().resolve("src/main.cc"),
                    "#include <iostream>\nint main(){int a,b;if(!(std::cin>>a>>b))return 2;std::cout<<a+b<<'\\n';}\n");
            helper.allowWrites();
            String compilation = sandbox(helper.build(), helper.uid(), "/opt/gcc/13.2.0/bin/g++",
                    List.of("src/main.cc", "-std=c++17", "-O2", "-static", "-o", "src/main"),
                    Path.of("/dev/null"), task.resolve("compile.out"), task.resolve("compile.err"),
                    16 * 1024 * 1024, false);
            try {
                successful(compilation);
            } catch (AssertionError failure) {
                throw new AssertionError("Helper compilation failed: "
                        + Files.readString(task.resolve("compile.err")), failure);
            }
            Path original = helper.build().resolve("src/main");
            if (!Integer.valueOf(helper.uid()).equals(Files.getAttribute(original, "unix:uid"))) {
                throw new AssertionError("Compiler did not run as its leased identity");
            }
            Object originalInode = Files.getAttribute(original, "unix:ino");
            helper.sealTo(sealed);
            Path executable = sealed.resolve("src/main");
            if (!Integer.valueOf(0).equals(Files.getAttribute(executable, "unix:uid"))
                    || originalInode.equals(Files.getAttribute(executable, "unix:ino"))) {
                throw new AssertionError("Helper was not copied into a fresh root-owned inode");
            }
            byte[] before = Files.readAllBytes(executable);
            sandbox(sealed, 65534, "/bin/sh", List.of("-c", "printf overwritten > src/main"),
                    Path.of("/dev/null"), task.resolve("write.out"), task.resolve("write.err"), 65536, false);
            if (!Arrays.equals(before, Files.readAllBytes(executable))
                    || !Files.readString(task.resolve("write.err")).contains("Permission denied")) {
                throw new AssertionError("Submission identity could modify the sealed helper");
            }
            Path input = task.resolve("input");
            Files.writeString(input, "17 25\n");
            String execution = sandbox(sealed, 65534, executable.toString(), List.of(), input,
                    task.resolve("run.out"), task.resolve("run.err"), 65536, true);
            successful(execution);
            if (!Files.readString(task.resolve("run.out")).equals("42\n")) {
                throw new AssertionError("Sealed nested helper did not execute correctly");
            }
            System.out.println("{\"helper_non_root_compilation\":true,\"helper_distinct_leases\":true,"
                    + "\"helper_fresh_root_inode\":true,\"helper_nobody_write_denied\":true,"
                    + "\"helper_nested_cpp_execution\":true}");
        }
    }
}
JAVA
java --class-path "$workspace/helper-classes/BOOT-INF/classes" \
    "$workspace/HelperRuntimeSmoke.java" "$workspace"
