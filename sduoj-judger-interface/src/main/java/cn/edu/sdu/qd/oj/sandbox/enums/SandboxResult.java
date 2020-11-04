package cn.edu.sdu.qd.oj.sandbox.enums;

import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import lombok.AllArgsConstructor;

@AllArgsConstructor
public enum SandboxResult {
    SUCCESS(0, "SUCCESS", SubmissionJudgeResult.AC),
    CPU_TIME_LIMIT_EXCEEDED(1, "CPU Time Limit Exceeded", SubmissionJudgeResult.TLE),
    REAL_TIME_LIMIT_EXCEEDED(2, "Real Time Limit Exceeded", SubmissionJudgeResult.TLE),
    MEMORY_LIMIT_EXCEEDED(3, "Memory Limit Exceeded", SubmissionJudgeResult.MLE),
    RUNTIME_ERROR(4, "Runtime Error", SubmissionJudgeResult.RE),
    SYSTEM_ERROR(5, "System Error", SubmissionJudgeResult.SE),
    ;

    public int code;
    public String message;
    public SubmissionJudgeResult submissionJudgeResult;

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
