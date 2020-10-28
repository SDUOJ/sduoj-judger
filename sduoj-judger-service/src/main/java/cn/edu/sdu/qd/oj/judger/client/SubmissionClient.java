package cn.edu.sdu.qd.oj.judger.client;

import cn.edu.sdu.qd.oj.submit.api.SubmissionApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = SubmissionApi.SERVICE_NAME, qualifier = "SubmissionClient")
public interface SubmissionClient extends SubmissionApi {
}
