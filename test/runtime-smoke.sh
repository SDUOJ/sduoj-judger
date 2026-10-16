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
int main() {
    long first, second;
    if (!(std::cin >> first >> second)) return 2;
    std::cout << first + second << "\n";
    std::cerr << "diagnostic\n";
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
