/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.manager;

import com.sduoj.judger.config.PathConfig;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;

@Slf4j
@Component
public class LocalZipManager implements CommandLineRunner {

    private final Set<Long> zipFileIds = new CopyOnWriteArraySet<>();

    @Override
    public void run(String... args) throws Exception {
        Files.list(Path.of(PathConfig.ZIP_DIR))
                .map(Path::getFileName)
                .map(Path::toString)
                .filter(o -> o.endsWith(".zip"))
                .map(o -> o.substring(0, o.length() - 4))
                .map(Long::parseLong)
                .forEach(zipFileIds::add);
        log.info("{}", zipFileIds);
    }

    public boolean isExist(Long zipFileId) {
        return zipFileIds.contains(zipFileId);
    }

    public void addZipFile(Long zipFileId) {
        zipFileIds.add(zipFileId);
    }

}
