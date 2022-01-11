/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.manager;

import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import com.google.common.collect.Sets;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.io.File;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Component
public class LocalZipManager implements CommandLineRunner {

    private Set<String> checkpoints;

    @Override
    public void run(String... args) throws Exception {
        checkpoints = Optional.ofNullable(PathConfig.ZIP_DIR)
                .map(File::new)
                .map(File::list)
                .map(Sets::newHashSet)
                .orElse(Sets.newHashSet());
        log.info("{}", checkpoints);
    }

    public boolean isExist(Long zipFileId) {
        return checkpoints.contains(zipFileId.toString());
    }

    public void addZipFile(Long checkpointId) {
        synchronized (checkpoints) {
            Optional.ofNullable(checkpointId).map(Objects::toString).ifPresent(checkpoints::add);
        }
    }

}
