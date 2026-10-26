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

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

import com.sduoj.filesys.dto.ByteDownloadRespDTO;
import feign.Response;
import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import org.junit.Test;
import org.springframework.boot.autoconfigure.http.HttpMessageConverters;
import org.springframework.cloud.openfeign.support.SpringDecoder;

public class ByteDownloadFeignDecodeTest {
    private List<ByteDownloadRespDTO> downloadList;

    @Test
    @SuppressWarnings("unchecked")
    public void springFeignDecoderReadsTheRealDownloadResponseType() throws Exception {
        var decoder = new SpringDecoder(() -> new HttpMessageConverters());
        var headers = Map.<String, Collection<String>>of("Content-Type", List.of("application/json"));
        var request = feign.Request.create(feign.Request.HttpMethod.POST, "http://filesys/byteDownloads",
                Map.of(), new byte[0], StandardCharsets.UTF_8, null);
        try (var response = Response.builder().status(200).reason("OK").request(request)
                .headers(headers).body("[{\"id\":\"9007199254740993\",\"bytes\":\"AP+AQQ==\"}]", StandardCharsets.UTF_8).build()) {
            var files = (List<ByteDownloadRespDTO>) decoder.decode(response,
                    getClass().getDeclaredField("downloadList").getGenericType());
            assertEquals(1, files.size());
            assertEquals(Long.valueOf(9007199254740993L), files.get(0).getId());
            assertArrayEquals(new byte[] {0, (byte) 255, (byte) 128, 65}, files.get(0).getBytes());
        }
    }
}
