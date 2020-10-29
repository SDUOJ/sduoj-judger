package cn.edu.sdu.qd.oj.judger.dto;

import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submit.enums.SubmissionJudgeResult;
import lombok.*;

import java.util.List;

@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class CommandExecuteResult extends BaseDTO {
    public OneJudgeResult toOneJudgeResult(Long submissionId) {
        return null;
    }
    public List<Integer> toList() {
        return null;
    }
}