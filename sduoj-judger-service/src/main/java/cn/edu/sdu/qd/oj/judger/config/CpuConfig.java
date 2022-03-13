/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.config;


import cn.edu.sdu.qd.oj.common.util.CollectionUtils;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;

import java.io.FileNotFoundException;
import java.util.HashSet;
import java.util.Set;
import java.util.stream.IntStream;

@Slf4j
public class CpuConfig {

    @Getter
    private static Set<Integer> cpuSet;

    private static final String[] CPUSET_PATHS = new String[]{
        "/sys/fs/cgroup/cpuset/cpuset.cpus",
        "/sys/fs/cgroup/cpuset.cpus"
    };

    public static void initialize() {
        for (String cpuSetPath : CPUSET_PATHS) {
            if (initialize(cpuSetPath)) {
                return;
            }
        }
        throw new RuntimeException("cpuset.cpus init failed");
    }

    public static boolean initialize(String cpuSetPath) {
        try {
            log.info("Reading cpuset.cpus from {}", cpuSetPath);
            String cpuSet = FileUtils.readFile(cpuSetPath); // 读出来是形如 '0-1,3-5' 之类的串，需要处理
            log.info("CpuConfig Read CpuSet: {}", cpuSet);
            CpuConfig.cpuSet = handleCpuSetString(cpuSet);
            log.info("CpuConfig Initialize: {}", CpuConfig.cpuSet);
            return true;
        } catch (SystemErrorException e) {
            if (e.getCause() instanceof FileNotFoundException) {
                log.warn("{} nou found", cpuSetPath);
            }
        }
        return false;
    }

    /**
     * 处理形如 '0-1,3-5' 的串，转换成集合
     */
    private static Set<Integer> handleCpuSetString(String cpuSetString) {
        Set<Integer> set = new HashSet<>();
        for (String str : cpuSetString.split(",")) {
            str = str.trim();
            if (StringUtils.isBlank(str)) {
                continue;
            }
            int index = str.indexOf('-');
            if (index != -1) {
                int begin = Integer.parseInt(str.substring(0, index));
                int end = Integer.parseInt(str.substring(index + 1));
                if (begin > end) {
                    int temp = end;
                    end = begin;
                    begin = temp;
                }
                IntStream.range(begin, end + 1).forEach(set::add);
            } else {
                set.add(Integer.parseInt(str));
            }
        }
        if (CollectionUtils.isEmpty(set)) {
            throw new RuntimeException("CpuSet init fail");
        }
        return set;
    }
}
