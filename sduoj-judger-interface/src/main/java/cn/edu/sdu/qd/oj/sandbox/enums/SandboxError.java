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

import lombok.AllArgsConstructor;

@AllArgsConstructor
public enum SandboxError {
    INVALID_CONFIG(1, "Invalid config"),
    FORK_FAILED(2, "Run fork() failed"),
    PTHREAD_FAILED(3, "Run child thread failed"),
    WAIT_FAILED(4, "Run wait4() failed"),
    DUP2_FAILED(5, "Run dup2() failed"),
    SETRLIMIT_FAILED(6, "Run setrlimit() failed"),
    SETUID_FAILED(7, "Run setuid() failed"),
    LOAD_SECCOMP_FAILED(8, "Load seccomp rules failed"),
    EXECVE_FAILED(9, "Run execve() failed"),
    SPJ_ERROR(10, "Run special judge failed"),
    ROOT_REQUIRED(11, "Sandbox needs root privilege"),
    NOBODY_REQUIRED(12, "User program needs run in NOBODY"),

    ;


    public int code;
    public String message;

    public boolean equals(Integer code) {
        if (code == null) {
            return false;
        }
        return this.code == code;
    }

    public static SandboxError of(Integer code) {
        for (SandboxError value : SandboxError.values()) {
            if (value.equals(code)) {
                return value;
            }
        }
        return null;
    }
}
