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
    private long cpuTime;
    private long realTime;
    private long memory;
    private int signal;
    private int exitCode;
    private int error;
    private int result;
}
