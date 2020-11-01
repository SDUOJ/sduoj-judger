package cn.edu.sdu.qd.oj.judger.client;

import cn.edu.sdu.qd.oj.checkpoint.api.CheckpointApi;
import cn.edu.sdu.qd.oj.problem.api.ProblemApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = CheckpointApi.SERVICE_NAME, qualifier = "CheckpointClient")
public interface CheckpointClient extends CheckpointApi {
}
