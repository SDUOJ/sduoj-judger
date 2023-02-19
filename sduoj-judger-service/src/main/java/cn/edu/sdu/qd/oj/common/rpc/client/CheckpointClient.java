/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.common.rpc.client;

import cn.edu.sdu.qd.oj.checkpoint.api.CheckpointApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = CheckpointApi.SERVICE_NAME)
public interface CheckpointClient extends CheckpointApi {
}
