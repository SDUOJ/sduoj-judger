/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.common.rpc.client;

import com.sduoj.submission.api.SubmissionApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = SubmissionApi.SERVICE_NAME)
public interface SubmissionClient extends SubmissionApi {
}
