package cn.edu.sdu.qd.oj.judger.config;

import cn.edu.sdu.qd.oj.judger.exception.SystemErrorException;
import cn.edu.sdu.qd.oj.judger.util.ProcessUtils;
import org.apache.commons.lang3.StringUtils;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * some utils for getting the infomation of the container which the judger is running in
 *
 * @author zhangt2333
 */
public class DockerContainers {

    private static String CONTAINER_ID = null;

    private static String CONTAINER_NAME = null;

    private static String[] CONTAINER_IPS = null;

    private static int NODE_INDEX = -1;

    private DockerContainers() {
    }

    public static String getContainerId() {
        if (CONTAINER_ID == null) {
            CONTAINER_ID = System.getenv("HOSTNAME");
            if (CONTAINER_ID == null) {
                throw new RuntimeException("Get container ip failed");
            }
        }
        return CONTAINER_ID;
    }

    public static String[] getContainerIps() throws SystemErrorException {
        if (CONTAINER_IPS == null) {
            ProcessUtils.ProcessStatus result = null;
            result = ProcessUtils.cmd(null, 2, "hostname", "-I");
            if (result.exitCode != 0) {
                throw new RuntimeException("Get container ip failed, command output: "
                        + result.output);
            }
            CONTAINER_IPS = Arrays.stream(result.output.split(" "))
                                  .filter(StringUtils::isNotBlank)
                                  .toArray(String[]::new);
        }
        return CONTAINER_IPS;
    }

    public static String getContainerName() throws SystemErrorException {
        if (CONTAINER_NAME == null) {
            // use DNS to get the container name
            Set<String> containerNames = new HashSet<>();
            for (String containerIp : getContainerIps()) {
                ProcessUtils.ProcessStatus result = ProcessUtils.cmd(null, 10,
                        "host", '"' + containerIp + '"');
                if (result.exitCode != 0) {
                    throw new RuntimeException("Get host failed, command output: "
                            + result.output);
                }
                // temp1, e.g., "container-name-1.network1."
                String temp1 = result.output.substring(result.output.lastIndexOf(' ') + 1);
                // temp2, e.g., "container-name-1"
                String temp2 = temp1.substring(0, temp1.indexOf('.'));
                containerNames.add(temp2);
            }
            if (containerNames.size() != 1) {
                throw new RuntimeException("Found zero or multiple container names, so confusing: "
                        + containerNames);
            }
            CONTAINER_NAME = containerNames.iterator().next();
        }
        return CONTAINER_NAME;
    }

    /**
     * @return a positive integer, the index of the container node
     */
    public static int getContainerNodeIndex() throws SystemErrorException {
        if (NODE_INDEX == -1) {
            String containerName = getContainerName();
            // "sduoj_judger_1" -> "1"
            String temp = containerName.substring(containerName.lastIndexOf('_') + 1);
            if (StringUtils.isNumeric(temp)) {
                NODE_INDEX = Integer.parseInt(temp);
                return NODE_INDEX;
            }
            // "sduoj_judger-1" -> "1"
            temp = containerName.substring(containerName.lastIndexOf('-') + 1);
            if (StringUtils.isNumeric(temp)) {
                NODE_INDEX = Integer.parseInt(temp);
                return NODE_INDEX;
            }
            if (NODE_INDEX == -1) {
                throw new RuntimeException("Get container node index failed, container name: "
                        + containerName);
            }
        }
        return NODE_INDEX;
    }
}
