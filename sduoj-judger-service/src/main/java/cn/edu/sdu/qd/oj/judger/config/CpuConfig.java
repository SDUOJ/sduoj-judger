package cn.edu.sdu.qd.oj.judger.config;


import cn.edu.sdu.qd.oj.common.util.CollectionUtils;
import cn.edu.sdu.qd.oj.judger.util.FileUtils;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang.StringUtils;

import java.util.HashSet;
import java.util.Set;
import java.util.stream.IntStream;

@Slf4j
public class CpuConfig {

    @Getter
    private static Set<Integer> cpuSet;   //     "/sys/fs/cgroup/cpuset/cpuset.cpus"

    public static void initialize() throws Throwable {
        String cpuSetString = FileUtils.readFile("/sys/fs/cgroup/cpuset/cpuset.cpus"); // 读出来是形如 '0-1,3-5' 之类的串，需要处理
        log.info("CpuConfig Read CpuSet: {}", cpuSetString);
        cpuSet = handleCpuSetString(cpuSetString);
        log.info("CpuConfig Initialize: {}", cpuSet);
    }

    /**
    * @Description 处理形如 '0-1,3-5' 的串，转换成集合
    **/
    private static Set<Integer> handleCpuSetString(String cpuSetString) {
        Set<Integer> set = new HashSet<>();
        for (String str : cpuSetString.split(",")) {
            str = str.trim();
            if (StringUtils.isBlank(str)) {
                continue;
            }
            int index = str.indexOf('-');
            if (index != -1) {
                int begin = Integer.parseInt(str.substring(0, index));
                int end = Integer.parseInt(str.substring(index + 1));
                if (begin > end) {
                    int temp = end;
                    end = begin;
                    begin = temp;
                }
                IntStream.range(begin, end + 1).forEach(set::add);
            } else {
                set.add(Integer.parseInt(str));
            }
        }
        if (CollectionUtils.isEmpty(set)) {
            throw new RuntimeException("CpuSet init fail");
        }
        return set;
    }
}
