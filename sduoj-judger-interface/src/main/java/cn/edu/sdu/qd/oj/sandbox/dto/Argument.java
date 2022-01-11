/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.sandbox.dto;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * sandbox argument builder
 *
 * @author zhangt2333
 * @author jeshrz
 */
public class Argument {

    private final Map<SandboxArgument, Object> args;

    private Argument() {
        this.args = new HashMap<>();
    }

    public Argument add(SandboxArgument key, Object value) throws SystemErrorException {
        if (key == null || value == null) {
            return this;
        }
        if (!key.clz.isInstance(value)) {
            throw new SystemErrorException(String.format("Unexpected sandbox argument type of %s: %s\n", key, value.getClass()));
        }
        args.put(key, value);
        return this;
    }

    public List<String> getFormatArgs() {
        List<String> list = new ArrayList<>();
        args.forEach((k, v) -> {
            if (String.class == k.clz) {
                list.add(String.format("--%s=\"%s\"", k, v));
            } else if (String[].class == k.clz) {
                for (String _v : (String[]) v) {
                    list.add(String.format("--%s=\"%s\"", k, _v));
                }
            } else {
                list.add(String.format("--%s=%s", k, v));
            }
        });
        return list;
    }

    public static Argument build() {
        return new Argument();
    }
}