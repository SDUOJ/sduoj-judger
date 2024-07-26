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
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;

import java.io.FileNotFoundException;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

@Slf4j
public class CpuConfig {

    public static final int CPU_PER_JUDGER;

    private static Collection<Integer> cpus;

    private static final String[] CPUSET_PATHS = new String[]{
        "/sys/fs/cgroup/cpuset/cpuset.cpus",
        "/sys/fs/cgroup/cpuset.cpus",
        "/sys/fs/cgroup/cpuset.cpus.effective"
    };

    static {
        String cpuPerJudger = System.getenv("CPU_PER_JUDGER");
        try {
            CPU_PER_JUDGER = Integer.parseInt(cpuPerJudger.trim());
        } catch (Throwable t) {
            throw new RuntimeException("env CPU_PER_JUDGER is not a number");
        }
    }

    private CpuConfig() {
    }

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

            // 读出来是形如 '0-1,3-5' 之类的串，需要处理
            String cpusStr = FileUtils.readFile(cpuSetPath);
            if (StringUtils.isBlank(cpusStr)) {
                log.warn("{} is empty", cpuSetPath);
                return false;
            }
            log.info("Parsing CpuSet: {}", cpusStr);

            List<Integer> cpus = handleCpuSetString(cpusStr);
            log.info("CpuSet: {}", cpus);

            // 分配 cpu 给当前 judger
            int containerNodeIndex = DockerContainers.getContainerNodeIndex();
            log.info("Getting {} CPUs for current container#{}", CPU_PER_JUDGER, containerNodeIndex);
            int fromIndex = (containerNodeIndex - 1) * CPU_PER_JUDGER;
            int toIndex = containerNodeIndex * CPU_PER_JUDGER;
            if (cpus.size() < toIndex) {
                log.error("Not enough {} CPUs for current container#{} in {}",
                        CPU_PER_JUDGER, containerNodeIndex, cpus);
                throw new SystemErrorException("Not enough CPUs for current container");
            }
            CpuConfig.cpus = cpus.subList(fromIndex, toIndex);
            log.info("CpuConfig Initialize: {}", CpuConfig.cpus);

            return true;
        } catch (SystemErrorException e) {
            if (e.getCause() instanceof FileNotFoundException) {
                log.warn("{} nou found", cpuSetPath);
            }
        }
        return false;
    }

    /**
     * solve the string like ''0-1,3-5' to a ordered collection of cpu ids
     */
    private static List<Integer> handleCpuSetString(String cpuSetString) {
        Set<Integer> cpus = new HashSet<>();
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
                IntStream.range(begin, end + 1).forEach(cpus::add);
            } else {
                cpus.add(Integer.parseInt(str));
            }
        }
        if (CollectionUtils.isEmpty(cpus)) {
            throw new RuntimeException("CpuSet init fail");
        }
        return cpus.stream().sorted().collect(Collectors.toList());
    }

    public static Collection<Integer> getCpuSet() {
        return cpus;
    }
}
