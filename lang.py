default_env = ["LANG=en_US.UTF-8", "LANGUAGE=en_US:en", "LC_ALL=en_US.UTF-8"]

c_lang_config = {
    "src_name": "solution.c",
    "exe_name": "solution",
    "compile_command": "/usr/bin/gcc -DONLINE_JUDGE -O2 -Wall -fmax-errors=3 -std=c99 -o {exe_name} {src_name} -lm",
    "run_command": "{exe_path}"
    "run_args": "",
    "seccomp_rules": "c_cpp",
}

cc_lang_config = {
    "src_name": "solution.cc",
    "exe_name": "solution",
    "compile_command": "/usr/bin/g++ -DONLINE_JUDGE -O2 -Wall -fmax-errors=3 -std=c++11 -o {exe_name} {src_name} -lm"
    "run_command": "{exe_path}"
    "run_args": "",
    "seccomp_rules": "c_cpp",
}

py2_lang_config = {
    "src_name": "solution.py",
    "exe_name": "solution.pyc",
    "compile_command": "/usr/bin/python -c \"import py_compile; py_compile.compile('{src_name}', '{exe_name}', doraise=True)\"",
    "run_command": "/usr/bin/python",
    "run_args": "{exe_path}",
    "seccomp_rules": "general",
}

py3_lang_config = {
    "src_name": "solution.py",
    "exe_name": "solution.pyc",
    "compile_command": "/usr/bin/python3 -c \"import py_compile; py_compile.compile('{src_name}', '{exe_name}', doraise=True)\"",
    "run_command": "/usr/bin/python3",
    "run_args": "{exe_path}",
    "seccomp_rules": "general",
}

java_lang_config = {
    "src_name": "solution.java",
    "exe_name": "solution.class",
    "compile_command": "",
    "run_command": "",
    "run_args": "",
    "seccomp_rules": "general",
}