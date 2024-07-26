package com.sduoj.judger.config;

import com.sduoj.judger.exception.SystemErrorException;
import com.sduoj.judger.util.ProcessUtils;
import com.sduoj.judger.util.ShellUtils;
import org.apache.commons.lang3.StringUtils;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * some utils for getting the information of the container which the judger is running in
 *
 * @author zhangt2333
 */
public class DockerContainers {

    private static final org.slf4j.Logger logger = org.slf4j.LoggerFactory.getLogger(DockerContainers.class);

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

    public static String[] getContainerIps() {
        if (CONTAINER_IPS == null) {
            ProcessUtils.CommandResult result = ShellUtils.execCmd("hostname", "-I");
            if (result.exitCode != 0) {
                throw new RuntimeException("Get container ip failed, command output: " +
                        result.stdout + "\n" + result.stderr);
            }
            CONTAINER_IPS = Arrays.stream(result.stdout.split(" "))
                                  .filter(StringUtils::isNotBlank)
                                  .toArray(String[]::new);
        }
        return CONTAINER_IPS;
    }

    public static String getContainerName() {
        if (CONTAINER_NAME == null) {
            // use DNS to get the container name
            Set<String> containerNames = new HashSet<>();
            for (String containerIp : getContainerIps()) {
                ProcessUtils.CommandResult result = ShellUtils.execCmd("host", '"' + containerIp + '"');
                if (result.exitCode == 0) {
                    // result.stdout, e.g., "79.19.0.10.in-addr.arpa domain name pointer sduoj_judger.1.n5l9a4x5kmqgr81lzpxfqux0n.sduoj_network."
                    // result.stdout, e.g., "7.3.190.172.in-addr.arpa domain name pointer sduoj_judger_1.sduoj_network."
                    String stdout = result.stdout;
                    // temp1, e.g., "sduoj_judger.1.n5l9a4x5kmqgr81lzpxfqux0n.sduoj_network."
                    // temp1, e.g., "sduoj_judger_1.sduoj_network."
                    String temp1 = stdout.substring(stdout.lastIndexOf(' ') + 1);
                    // temp2, e.g., "sduoj_judger.1.n5l9a4x5kmqgr81lzpxfqux0n"
                    // temp2, e.g., "sduoj_judger_1"
                    String temp2 = temp1.substring(0, temp1.lastIndexOf('.', temp1.lastIndexOf('.') - 1));
                    containerNames.add(temp2);
                    logger.info("Get container name: {}", temp2);
                } else {
                    logger.warn("Get container name failed, command output: {}\n{}",
                            result.stdout, result.stderr);
                }
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
            String temp;
            // "sduoj_judger.1.n5l9a4x5kmqgr81lzpxfqux0n" -> "1"
            int i1 = containerName.indexOf('.');
            int i2 = containerName.lastIndexOf('.');
            if (i1 != -1 && i2 != -1 && i1 != i2) {
                temp = containerName.substring(i1 + 1, i2);
                if (StringUtils.isNumeric(temp)) {
                    NODE_INDEX = Integer.parseInt(temp);
                    return NODE_INDEX;
                }
            }
            // "sduoj_judger_1" -> "1"
            int i = containerName.lastIndexOf('_');
            if (i != -1) {
                temp = containerName.substring(i + 1);
                if (StringUtils.isNumeric(temp)) {
                    NODE_INDEX = Integer.parseInt(temp);
                    return NODE_INDEX;
                }
            }
            // "sduoj_judger-1" -> "1"
            i = containerName.lastIndexOf('-');
            if (i != -1) {
                temp = containerName.substring(i + 1);
                if (StringUtils.isNumeric(temp)) {
                    NODE_INDEX = Integer.parseInt(temp);
                    return NODE_INDEX;
                }
            }
            if (NODE_INDEX == -1) {
                throw new RuntimeException("Get container node index failed, container name: "
                        + containerName);
            }
        }
        return NODE_INDEX;
    }
}
