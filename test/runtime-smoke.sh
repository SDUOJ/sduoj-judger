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
    --max_output_size=65536 --exe_path="$workspace/main" \
    --input_path="$workspace/input" --output_path="$workspace/output" \
    --error_path="$workspace/error" --seccomp_rules=c_cpp \
    --uid=65534 --gid=65534 > "$workspace/result.json"
python3 - "$workspace" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
result = json.loads((root / 'result.json').read_text())
expected = {'cpu_time', 'real_time', 'memory', 'signal', 'exit_code', 'error', 'result'}
assert set(result) == expected, result
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
        --max_output_size=65536 --exe_path="$workspace/main" \
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
assert set(result) == {'cpu_time', 'real_time', 'memory', 'signal', 'exit_code', 'error', 'result'}, result
assert result['signal'] == signal.SIGSYS and result['result'] == 4 and result['error'] == 0, result
# Matching output proves the program reached the probe after ordinary C++ startup.
assert (root / (probe + '.out')).read_text() == '42\n'
assert (root / (probe + '.err')).read_text() == 'diagnostic\n'
assert not target.exists(), target
print(json.dumps({'denied_probe': probe, 'sandbox': result}))
PY
done
