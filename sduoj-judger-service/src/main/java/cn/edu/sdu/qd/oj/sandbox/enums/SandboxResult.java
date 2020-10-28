package cn.edu.sdu.qd.oj.sandbox.enums;

import lombok.AllArgsConstructor;

@AllArgsConstructor
public enum SandboxResult {
    SUCCESS(0, "SUCCESS"),
    CPU_TIME_LIMIT_EXCEEDED(1, "CPU Time Limit Exceeded"),
    REAL_TIME_LIMIT_EXCEEDED(2, "Real Time Limit Exceeded"),
    MEMORY_LIMIT_EXCEEDED(3, "Memory Limit Excedded"),
    RUNTIME_ERROR(4, "Runtime Error"),
    SYSTEM_ERROR(5, "System Error"),
    ;

    public int code;
    public String message;

    public boolean equals(Integer code) {
        if (code == null) {
            return false;
        }
        return this.code == code;
    }

    public static SandboxResult of(Integer code) {
        for (SandboxResult value : SandboxResult.values()) {
            if (value.equals(code)) {
                return value;
            }
        }
        return null;
    }
}
