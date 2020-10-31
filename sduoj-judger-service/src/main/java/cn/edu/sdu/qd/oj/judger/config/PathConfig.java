package cn.edu.sdu.qd.oj.judger.config;

import org.springframework.context.annotation.Configuration;

import java.nio.file.Paths;

@Configuration
public class PathConfig {
    public static final String SANDBOX_PATH = "/usr/bin/sandbox";
    public static final String WORKSPACE_DIR = "/workspace";
    public static final String LOG_DIR = "/log";
    public static final String DATA_DIR = "/data";


    public static final String SANDBOX_LOG_PATH = Paths.get(LOG_DIR, "sandbox.log").toString();
    public static final String JUDGER_LOG_PATH = Paths.get(LOG_DIR, "judger.log").toString();

    public static final int NOBODY_UID = 65534;
    public static final int NOBODY_GID = 65534;
}
