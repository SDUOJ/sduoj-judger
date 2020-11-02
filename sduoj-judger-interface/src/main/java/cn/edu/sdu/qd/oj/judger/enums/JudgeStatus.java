package cn.edu.sdu.qd.oj.judger.enums;

import lombok.AllArgsConstructor;

@AllArgsConstructor
public enum JudgeStatus {
    COMPILING(-3),
    JUDGING(-2),
    END(-1),
    ;

    public int code;
}
