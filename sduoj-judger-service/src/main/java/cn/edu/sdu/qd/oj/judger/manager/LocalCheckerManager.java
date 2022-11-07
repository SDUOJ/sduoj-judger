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
import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import cn.edu.sdu.qd.oj.judger.util.ShellUtils;
import com.google.common.collect.Sets;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.io.File;
import java.nio.file.Paths;
import java.util.Set;

@Slf4j
@Component
public class LocalCheckerManager implements CommandLineRunner {

    private final Set<String> checkers = Sets.newHashSet();

    private final Set<String> checkerSources = Sets.newHashSet();

    @Override
    public void run(String... args) throws Exception {
        try {
            for (String filename : new File(PathConfig.CHECKER_DIR).list()) {
                if (filename.contains(".")) {
                    checkerSources.add(filename);
                } else {
                    checkers.add(filename);
                }
            }
        } catch (Throwable ignore) {
        }
        log.info("checkers: {}", checkers);
    }

    public boolean isCheckerExist(String checker) {
        if (checkerSources.contains(checker)) {
            checker = checker.substring(0, checker.indexOf('.'));
        }
        return checkers.contains(checker);
    }

    public boolean isCheckerSourceFilenameExist(String checkerSourceFilename) {
        return checkerSources.contains(checkerSourceFilename);
    }

    public void addCheckpoint(String checker) {
        if (checkerSources.contains(checker)) {
            checker = checker.substring(0, checker.indexOf('.'));
        }
        synchronized (this.checkers) {
            this.checkers.add(checker);
        }
    }

    public void compilePredefinedChecker(String checkerSourceFilename) throws CompileErrorException {
        String checkerBinary = checkerSourceFilename.substring(0, checkerSourceFilename.indexOf('.'));
        ProcessUtils.CommandResult result = ShellUtils.execCmd("/usr/bin/g++", "-I/",
                "-DONLINE_JUDGE", "-O2", "-w", "-fmax-errors=3", "-std=c++14",
                Paths.get(PathConfig.CHECKER_DIR, checkerSourceFilename).toString(), "-lm",
                "-o", Paths.get(PathConfig.CHECKER_DIR, checkerBinary).toString());
        if (result.exitCode != 0) {
            throw new CompileErrorException("checker compile error! please contract admin!");
        }
        addCheckpoint(checkerSourceFilename);
    }
}
