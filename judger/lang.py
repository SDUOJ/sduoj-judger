default_run_env = ["LANG=en_US.UTF-8", "LANGUAGE=en_US:en", "LC_ALL=en_US.UTF-8"]

_c_lang_config = {
    "src_name": "solution.c",
    "exe_name": "solution",

    "compile_command": "/usr/bin/gcc -DONLINE_JUDGE -O2 -Wall -fmax-errors=3 -std=c99 -o \"{exe_path}\" \"{src_path}\" -lm",
    "compile_cpu_time": 3000,
    "compile_real_time": 5000,
    "compile_memory": 512 * 1024 * 1024,

    "run_command": "{exe_path}",
    "run_args": [],
    "run_envs": default_run_env,
    "seccomp_rules": "c_cpp",
}

_cc_lang_config = {
    "src_name": "solution.cc",
    "exe_name": "solution",

    "compile_command": "/usr/bin/g++ -DONLINE_JUDGE -O2 -Wall -fmax-errors=3 -std=c++11 -o \"{exe_path}\" \"{src_path}\" -lm",
    "compile_cpu_time": 3000,
    "compile_real_time": 5000,
    "compile_memory": 512 * 1024 * 1024,

    "run_command": "{exe_path}",
    "run_args": [],
    "run_envs": default_run_env,
    "seccomp_rules": "c_cpp",
}

_py2_lang_config = {
    "src_name": "solution.py",
    "exe_name": "solution.pyc",

    "compile_command": "/usr/bin/python -c \"import py_compile; py_compile.compile('{src_path}', '{exe_path}', doraise=True)\"",
    "compile_cpu_time": 3000,
    "compile_real_time": 5000,
    "compile_memory": 512 * 1024 * 1024,

    "run_command": "/usr/bin/python",
    "run_args": ["{exe_path}"],
    "run_envs": default_run_env,
    "seccomp_rules": "general",
}

_py3_lang_config = {
    "src_name": "solution.py",
    "exe_name": "solution.pyc",

    "compile_command": "/usr/bin/python3 -c \"import py_compile; py_compile.compile('{src_path}', '{exe_path}', doraise=True)\"",
    "compile_cpu_time": 3000,
    "compile_real_time": 5000,
    "compile_memory": 512 * 1024 * 1024,

    "run_command": "/usr/bin/python3",
    "run_args": ["{exe_path}"],
    "run_envs": default_run_env,
    "seccomp_rules": "general",
}

_java_lang_config = {
    "src_name": "solution.java",
    "exe_name": "solution.class",

    "compile_command": "",
    "compile_cpu_time": 3000,
    "compile_real_time": 5000,
    "compile_memory": 512 * 1024 * 1024,

    "run_command": "",
    "run_args": [],
    "run_envs": default_run_env,
    "seccomp_rules": "general",
}

LANG_CONFIG = {
    "c": _c_lang_config,
    "cc": _cc_lang_config,
    "py2": _py2_lang_config,
    "py3": _py3_lang_config,
    "java": _java_lang_config
}

LANG_TYPE = ["c","cc","py2","py3","java"]