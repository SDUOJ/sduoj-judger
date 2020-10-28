package cn.edu.sdu.qd.oj;

import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.ShellUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.openfeign.EnableFeignClients;

import java.util.Properties;

@Slf4j
@SpringBootApplication
@EnableDiscoveryClient
@EnableFeignClients
public class JudgerApplication {

    public static void main(String[] args) {
        judgeLinuxOS();
        initBaseDirectory();
        SpringApplication.run(JudgerApplication.class, args);
    }

    private static void judgeLinuxOS() {
        try{
            Properties props = System.getProperties(); //获得系统属性集
            String osName = (String) props.get("os.name");
            if (!osName.toLowerCase().contains("linux")) {
                log.error("OS isn't Linux, but {}", osName);
                System.exit(-1);
            }
        } catch (Throwable t) {
            log.error("", t);
            System.exit(-1);
        }
    }


    private static void initBaseDirectory() {
        try {
            ShellUtils.createDir(PathConfig.LOG_DIR);
            ShellUtils.createDir(PathConfig.DATA_DIR);
            ShellUtils.createDir(PathConfig.WORKSPACE_DIR);
            ShellUtils.chmod(PathConfig.WORKSPACE_DIR, "711");
        } catch (Throwable t) {
            log.error("{}", t);
            System.exit(-1);
        }
    }
}
