package cn.edu.sdu.qd.oj.sandbox.dto;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;

public class Argument {
    public SandboxArgument key;
    public Object value;

    public Argument(SandboxArgument key, Object value) throws SystemErrorException {
        this.key = key;
        try {
            this.value = key.clz.cast(value);
        } catch (Exception e) {
            throw new SystemErrorException(String.format("Unexpected sandbox argument type of %s: %s\n", this.key, value.getClass()));
        }
    }
}
