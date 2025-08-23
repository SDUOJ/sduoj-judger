/*
 * Copyright 2020-2021 the original author or authors.
 *
 * Licensed under the General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/gpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.config;

import org.springframework.context.annotation.Configuration;

import java.nio.file.Paths;

@Configuration
public class PathConfig {
    //public static final String BASE_PATH = "/Users/rajeev/Desktop/judge_experiments/SDUOJ/";
    public static final String BASE_PATH = "";
    public static final String SANDBOX_PATH = "/usr/bin/sandbox";
    public static final String WORKSPACE_DIR = BASE_PATH + "/workspace";
    public static final String LOG_DIR =  BASE_PATH + "/log";
    public static final String DATA_DIR =  BASE_PATH + "/data";
    public static final String ZIP_DIR =  BASE_PATH + "/zip";


    public static final String SANDBOX_LOG_PATH = Paths.get(LOG_DIR, "sandbox.log").toString();
    public static final String JUDGER_LOG_PATH = Paths.get(LOG_DIR, "judger.log").toString();

    public static final int NOBODY_UID = 65534;
    public static final int NOBODY_GID = 65534;
}
