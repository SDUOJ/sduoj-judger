package cn.edu.sdu.qd.oj.sandbox.enums;

import lombok.AllArgsConstructor;

@AllArgsConstructor
public enum SandboxArgument {
    MAX_CPU_TIME("max_cpu_time", Integer.class),
    MAX_REAL_TIME("max_real_time", Integer.class),
    MAX_MEMORY("max_memory", Long.class),
    MAX_STACK("max_stack", Long.class),
    MAX_PROCESS_NUMBER("max_process_number", Integer.class),
    MAX_OUTPUT_SIZE("max_output_size", Integer.class),
    UID("uid", Integer.class),
    GID("gid", Integer.class),

    EXE_PATH("exe_path", String.class),
    INPUT_PATH("input_path", String.class),
    OUTPUT_PATH("output_path", String.class),
    SECCOMP_RULES("seccomp_rules", String.class),

    // may occur many times
    EXE_ARGS("exe_args", String[].class),
    EXE_ENVS("exe_envs", String[].class);

    public String arg;
    public Class<?> clz;

    public boolean equals(String arg) {
        if (arg == null) {
            return false;
        }
        return this.arg.equals(arg);
    }


    public String toString() {
        return this.arg;
    }

}
