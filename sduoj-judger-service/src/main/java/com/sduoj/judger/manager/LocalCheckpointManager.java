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
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.io.File;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

@Slf4j
@Component
public class LocalCheckpointManager implements CommandLineRunner {

    private final Set<String> checkpoints = new HashSet<>();

    @Override
    public void run(String... args) throws Exception {
        Set<String> checkpointFileNames = Optional.ofNullable(PathConfig.DATA_DIR)
                .map(File::new)
                .map(File::list)
                .map(Arrays::stream)
                .map(o -> o.filter(s -> s.endsWith(".in") || s.endsWith(".ans"))
                        .collect(Collectors.toSet()))
                .orElse(new HashSet<>());
        checkpointFileNames.forEach(o -> {
            if (o.endsWith(".in")) {
                String id = o.substring(0, o.length() - 3);
                if (checkpointFileNames.contains(id + ".ans")) {
                    checkpoints.add(id);
                }
            }
        });
        log.info("{}", checkpoints);
    }

    public boolean isCheckpointExist(Long checkpointId) {
        return checkpoints.contains(checkpointId.toString());
    }

    public void addCheckpoint(Long checkpointId) {
        synchronized (checkpoints) {
            Optional.ofNullable(checkpointId).map(Objects::toString).ifPresent(checkpoints::add);
        }
    }

}