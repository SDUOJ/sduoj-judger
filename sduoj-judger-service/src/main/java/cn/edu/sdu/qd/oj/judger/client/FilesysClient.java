package cn.edu.sdu.qd.oj.judger.client;

import cn.edu.sdu.qd.oj.api.FilesysApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = FilesysApi.SERVICE_NAME, qualifier = "FilesysClient")
public interface FilesysClient extends FilesysApi {
}
