package cn.edu.sdu.qd.oj.sandbox.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class SandboxResultDTO {
    private int cpuTime;
    private int realTime;
    private int memory;
    private int signal;
    private int exitCode;
    private int error;
    private int result;

    public int getMemory() {
        return memory / 1024;
    }
}
