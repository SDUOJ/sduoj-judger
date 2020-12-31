/*
 * Copyright 2020-2021 the original author or authors.
 *
 * Licensed under the General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/gpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj;

import cn.edu.sdu.qd.oj.judger.config.CpuConfig;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.openfeign.EnableFeignClients;

import java.util.Properties;

@Slf4j
@SpringBootApplication
@EnableDiscoveryClient
@EnableFeignClients
public class JudgerApplication {

    public static void main(String[] args) {
        judgeLinuxOS();
        initBaseDirectory();
        initCpuAffinity();
        SpringApplication.run(JudgerApplication.class, args);
    }

    private static void judgeLinuxOS() {
        try{
            Properties props = System.getProperties(); //获得系统属性集
            String osName = (String) props.get("os.name");
            if (!osName.toLowerCase().contains("linux")) {
                log.error("OS isn't Linux, but {}", osName);
                System.exit(-1);
            }
        } catch (Throwable t) {
            log.error("", t);
            System.exit(-1);
        }
    }


    private static void initBaseDirectory() {
        try {
            FileUtils.createDir(PathConfig.LOG_DIR);
            FileUtils.createDir(PathConfig.DATA_DIR);
            FileUtils.createDir(PathConfig.ZIP_DIR);
            FileUtils.createDir(PathConfig.WORKSPACE_DIR);
            ProcessUtils.chmod(PathConfig.WORKSPACE_DIR, "711");
        } catch (Throwable t) {
            log.error("", t);
            System.exit(-1);
        }
    }

    private static void initCpuAffinity() {
        try {
            CpuConfig.initialize();
        } catch (Throwable t) {
            log.error("", t);
            System.exit(-1);
        }
    }
}
