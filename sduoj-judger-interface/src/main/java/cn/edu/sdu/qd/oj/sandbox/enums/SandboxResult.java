/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.sandbox.enums;

import cn.edu.sdu.qd.oj.submission.enums.SubmissionJudgeResult;
import lombok.AllArgsConstructor;

@AllArgsConstructor
public enum SandboxResult {
    SUCCESS(0, "SUCCESS", SubmissionJudgeResult.AC),
    CPU_TIME_LIMIT_EXCEEDED(1, "CPU Time Limit Exceeded", SubmissionJudgeResult.TLE),
    REAL_TIME_LIMIT_EXCEEDED(2, "Real Time Limit Exceeded", SubmissionJudgeResult.TLE),
    MEMORY_LIMIT_EXCEEDED(3, "Memory Limit Exceeded", SubmissionJudgeResult.MLE),
    RUNTIME_ERROR(4, "Runtime Error", SubmissionJudgeResult.RE),
    SYSTEM_ERROR(5, "System Error", SubmissionJudgeResult.SE),
    OUTPUT_LIMIT_EXCEEDED(6, "Output Limit Exceeded", SubmissionJudgeResult.OLE)
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
        return SYSTEM_ERROR;
    }
}
