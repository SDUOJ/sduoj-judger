package cn.edu.sdu.qd.oj.judger.handler;

import cn.edu.sdu.qd.oj.judger.exception.CompileErrorException;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.ShellUtils;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateConfigDTO;
import cn.edu.sdu.qd.oj.judgetemplate.dto.JudgeTemplateDTO;
import cn.edu.sdu.qd.oj.judgetemplate.enums.JudgeTemplateTypeEnum;
import cn.edu.sdu.qd.oj.sandbox.service.SandboxService;
import cn.edu.sdu.qd.oj.sandbox.dto.Argument;
import cn.edu.sdu.qd.oj.sandbox.dto.SandboxResultDTO;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxArgument;
import cn.edu.sdu.qd.oj.sandbox.enums.SandboxResult;
import cn.edu.sdu.qd.oj.submit.dto.SubmissionUpdateReqDTO;
import com.alibaba.fastjson.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.nio.file.Paths;
import java.util.Arrays;


@Slf4j
@Component
public class IOSubmissionHandler extends SubmissionHandler {

    private String judgeLog;
    private String exePath;
    private JudgeTemplateConfigDTO judgeTemplateConfigDTO;

    @Autowired
    private SandboxService sandboxService;


    @Override
    public JudgeTemplateTypeEnum getSupportJudgeTemplateType() {
        return JudgeTemplateTypeEnum.IO;
    }

    @Override
    public SubmissionUpdateReqDTO start(JudgeTemplateDTO judgeTemplateDTO) throws CompileErrorException, SystemErrorException {
        judgeTemplateConfigDTO = JSON.parseObject(judgeTemplateDTO.getShellScript(), JudgeTemplateConfigDTO.class);
        // 编译
        compile();

        SubmissionUpdateReqDTO result = new SubmissionUpdateReqDTO();
        result.setJudgeLog(judgeLog);
        return result;
    }

    private void compile() throws CompileErrorException {
        try {
            JudgeTemplateConfigDTO.TemplateConfig.Compile compileConfig = judgeTemplateConfigDTO.getUser().getCompile();
            String srcPath = compileConfig.getSrcName();
            String code = submissionMessageDTO.getCode();
            ShellUtils.writeFile(srcPath, code);
            ShellUtils.chown(srcPath, "nobody");
            ShellUtils.chmod(srcPath, "400");

            log.info(String.format("Compiling \"%s\"", srcPath));

            exePath = Paths.get(workspaceDir, compileConfig.getExeName()).toString();
            String compilerLogPath = Paths.get(workspaceDir, "compiler.out").toString();
            String[] exeEnvs = new String[1];
            exeEnvs[0] = "PATH=" + System.getenv("PATH");

            StringBuilder sb = new StringBuilder();

            for (String eachCompileCommand : compileConfig.getCommands()) {
                String[] _commands = eachCompileCommand.split(" ");

                Argument[] _args = new Argument[10];
                _args[0] = new Argument(SandboxArgument.MAX_CPU_TIME, compileConfig.getMaxCpuTime());       /* max_cpu_time     */
                _args[1] = new Argument(SandboxArgument.MAX_REAL_TIME, compileConfig.getMaxRealTime());     /* max_real_time    */
                _args[2] = new Argument(SandboxArgument.MAX_MEMORY, compileConfig.getMaxMemory());          /* max_memory       */
                _args[3] = new Argument(SandboxArgument.MAX_STACK, 134217728 /* 128 * 1024 * 1024 */);      /* max_stack        */
                _args[4] = new Argument(SandboxArgument.MAX_OUTPUT_SIZE, 1048576 /* 1024 * 1024 */);        /* max_output_size  */
                _args[5] = new Argument(SandboxArgument.EXE_PATH, _commands[0]);                            /* exe_path         */
                _args[6] = new Argument(SandboxArgument.EXE_ARGS, Arrays.copyOfRange(_commands, 1, _commands.length));
                _args[7] = new Argument(SandboxArgument.EXE_ENVS, exeEnvs);                                 /* exe_envs         */
                _args[8] = new Argument(SandboxArgument.INPUT_PATH, "/dev/null");                           /* input_path       */
                _args[9] = new Argument(SandboxArgument.OUTPUT_PATH, compilerLogPath);                      /* output_path      */

                SandboxResultDTO sandboxResultDTO = sandboxService.run(0, _args);
                if (sandboxResultDTO == null) {
                    throw new SystemErrorException(String.format("Can not launch sandbox for command \"%s\"", eachCompileCommand));
                }

                try {
                    sb.append(ShellUtils.readFile(compilerLogPath)).append("\n");
                } catch (SystemErrorException e) {
                    throw new CompileErrorException(sb.toString());
                }

                if (!SandboxResult.SUCCESS.equals(sandboxResultDTO.getResult())) {
                    throw new CompileErrorException(sb.toString());
                }
            }
            log.info(String.format("Compiled \"%s\"", exePath));
            ShellUtils.chown(exePath, "nobody");
            ShellUtils.chmod(exePath, "500");
            judgeLog = sb.toString();
        } catch (SystemErrorException e) {
            throw new CompileErrorException(e);
        }
    }
}
