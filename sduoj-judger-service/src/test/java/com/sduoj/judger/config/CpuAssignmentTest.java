package com.sduoj.judger.config;

import org.junit.Test;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

public class CpuAssignmentTest {
    @Test
    public void explicitNodeDoesNotRunReverseDnsDiscovery() throws Exception {
        assertEquals(1, CpuAssignment.nodeIndex("1", () -> {
            throw new AssertionError("Host-network VM names must not determine CPU index");
        }));
        assertEquals(2, CpuAssignment.nodeIndex(null, () -> 2));
    }

    @Test
    public void invalidConfigurationFailsBeforeDiscovery() {
        for (String value : List.of("", "0", "-1", "node1", "999999999999999999")) {
            assertThrows(IllegalArgumentException.class,
                    () -> CpuAssignment.nodeIndex(value, () -> 1));
        }
    }

    @Test
    public void selectionRespectsRestrictedNonzeroCpuIdsAndRejectsOverflow() {
        assertEquals(List.of(4), CpuAssignment.select(List.of(4, 5), 1, 1));
        assertEquals(List.of(6), CpuAssignment.select(List.of(6, 7), 1, 1));
        assertEquals(List.of(5), CpuAssignment.select(List.of(4, 5), 1, 2));
        for (int[] pair : List.of(new int[]{1, 20261028}, new int[]{0, 1},
                new int[]{1, 0}, new int[]{Integer.MAX_VALUE, Integer.MAX_VALUE})) {
            assertThrows(IllegalArgumentException.class,
                    () -> CpuAssignment.select(List.of(4, 5), pair[0], pair[1]));
        }
    }
}
