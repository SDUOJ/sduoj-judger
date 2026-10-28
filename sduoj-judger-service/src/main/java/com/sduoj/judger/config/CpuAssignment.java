package com.sduoj.judger.config;

import java.util.List;
import com.sduoj.judger.exception.SystemErrorException;

/** Select CPUs only from the process's effective cpuset. */
final class CpuAssignment {
    private CpuAssignment() {
    }

    interface Discovery {
        int get() throws SystemErrorException;
    }

    static int nodeIndex(String configured, Discovery discovery) throws SystemErrorException {
        int index;
        if (configured == null) {
            index = discovery.get();
        } else {
            try {
                index = Integer.parseInt(configured.trim());
            } catch (NumberFormatException error) {
                throw new IllegalArgumentException("SDUOJ_JUDGER_CPU_NODE_INDEX must be a positive integer", error);
            }
        }
        if (index < 1) {
            throw new IllegalArgumentException("Judger CPU node index must be positive");
        }
        return index;
    }

    static List<Integer> select(List<Integer> available, int count, int nodeIndex) {
        long end = (long) count * nodeIndex;
        if (count < 1 || nodeIndex < 1 || end > available.size()) {
            throw new IllegalArgumentException("Judger CPU allocation exceeds its effective cpuset");
        }
        return List.copyOf(available.subList((int) end - count, (int) end));
    }
}
