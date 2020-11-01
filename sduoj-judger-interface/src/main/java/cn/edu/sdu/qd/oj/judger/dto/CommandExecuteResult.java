package cn.edu.sdu.qd.oj.judger.dto;

import lombok.*;

@Getter
public class CommandExecuteResult<V> extends BaseDTO {

    private final V result;

    public CommandExecuteResult(V result) {
        this.result = result;
    }
}