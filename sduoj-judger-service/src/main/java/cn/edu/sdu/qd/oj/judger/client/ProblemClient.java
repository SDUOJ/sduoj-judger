package cn.edu.sdu.qd.oj.judger.client;

import cn.edu.sdu.qd.oj.problem.api.ProblemApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = ProblemApi.SERVICE_NAME, qualifier = "ProblemClient")
public interface ProblemClient extends ProblemApi {
}
