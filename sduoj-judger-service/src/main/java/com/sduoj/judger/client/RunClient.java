/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.client;

import com.sduoj.submission.api.RunApi;

import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = RunApi.SERVICE_NAME, contextId = "runClient")
public interface RunClient extends RunApi {}
