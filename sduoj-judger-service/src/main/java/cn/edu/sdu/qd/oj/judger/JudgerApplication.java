/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger;

import cn.edu.sdu.qd.oj.common.mq.EnableMqModule;
import cn.edu.sdu.qd.oj.common.rpc.EnableRpcModule;
import cn.edu.sdu.qd.oj.judger.config.CpuConfig;
import cn.edu.sdu.qd.oj.judger.config.DockerContainers;
import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import cn.edu.sdu.qd.oj.judger.util.ShellUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

import java.util.Properties;

@Slf4j
@EnableMqModule
@EnableRpcModule
@EnableDiscoveryClient
@SpringBootApplication
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
            ShellUtils.chmod(PathConfig.WORKSPACE_DIR, "711");
        } catch (Throwable t) {
            log.error("", t);
            System.exit(-1);
        }
    }

    private static void initCpuAffinity() {
        try {
            log.info("Container {} '{}' is running", DockerContainers.getContainerId(),
                    DockerContainers.getContainerName());
            CpuConfig.initialize();
        } catch (Throwable t) {
            log.error("", t);
            System.exit(-1);
        }
    }
}
