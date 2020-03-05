sandbox_path = "../sduoj-sandbox/sandbox"

compile_config = {
    "cc": "g++ {} -o {} --static -O2",
    "py": "/usr/bin/python3 {}",
}

JUDGE_RESULT = [
    "Accepted",
    "CPU Time Limit Exceeded",
    "Real Time Limit Exceeded",
    "Memry Limit Exceeded",
    "Runtime Error",
    "System Error",
    "Output Limit Exceeded",
    "Wrong Answer",
    "Presentation Error",
]