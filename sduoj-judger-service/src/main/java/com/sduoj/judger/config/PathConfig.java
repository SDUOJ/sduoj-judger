/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.config;

import org.springframework.context.annotation.Configuration;

import java.nio.file.Paths;

@Configuration
public class PathConfig {
    public static final String SANDBOX_PATH = "/usr/bin/sandbox";
    public static final String WORKSPACE_DIR = "/workspace";
    public static final String LOG_DIR = "/log";
    public static final String DATA_DIR = "/data";
    public static final String ZIP_DIR = "/zip";
    public static final String CHECKER_DIR = "/checkers";


    public static final String SANDBOX_LOG_PATH = Paths.get(LOG_DIR, "sandbox.log").toString();
    public static final String JUDGER_LOG_PATH = Paths.get(LOG_DIR, "judger.log").toString();

    public static final int NOBODY_UID = 65534;
    public static final int NOBODY_GID = 65534;
}
