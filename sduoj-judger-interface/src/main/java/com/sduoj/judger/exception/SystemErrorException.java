/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.exception;

public class SystemErrorException extends Exception {
    public SystemErrorException() {
        super();
    }

    public SystemErrorException(String message, Throwable cause) {
        super(message, cause);
    }

    public SystemErrorException(String message) {
        super(message);
    }

    public SystemErrorException(Throwable cause) {
        super(cause);
    }
}