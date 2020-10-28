package cn.edu.sdu.qd.oj.judger.client;

import cn.edu.sdu.qd.oj.judgetemplate.api.JudgeTemplateApi;
import org.springframework.cloud.openfeign.FeignClient;

@FeignClient(value = JudgeTemplateApi.SERVICE_NAME, qualifier = "JudgeTemplateClient")
public interface JudgeTemplateClient extends JudgeTemplateApi {
}
