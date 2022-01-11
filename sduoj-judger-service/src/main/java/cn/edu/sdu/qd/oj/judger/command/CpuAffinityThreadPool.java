/*
 * Copyright 2020-2022 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.command;

import cn.edu.sdu.qd.oj.judger.config.CpuConfig;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Queue;
import java.util.concurrent.*;

/**
 * for the CPU-Affinity command scheduling and execution
 *
 * @author zhangt2333
 */
@Slf4j
@Component
public class CpuAffinityThreadPool {

    // CPU 池
    private final Queue<Integer> cpuPool;

    // 线程池
    private final CompletionService<CommandResult> threadPool;

    /**
     * @Description 提交一个异步任务
     **/
    public void submit(CpuAffinityCommand cpuAffinityCommand) {
        threadPool.submit(new CommandThread(cpuAffinityCommand, cpuPool));
    }

    /**
     * 获取一个任务的执行结果，顺序任意取决于任务完成顺序
     * @return cn.edu.sdu.qd.oj.judger.dto.CommandExecResult
     **/
    public CommandResult take() throws InterruptedException, ExecutionException {
        return threadPool.take().get();
    }

    public CpuAffinityThreadPool() {
        // 初始化 cpu 池
        cpuPool = new LinkedBlockingDeque<>(CpuConfig.getCpuSet());
        // 初始化线程池
        threadPool = new ExecutorCompletionService<>(new ThreadPoolExecutor(
                cpuPool.size(),
                cpuPool.size(),
                0,
                TimeUnit.SECONDS,
                new LinkedBlockingQueue<>(1024),
                new ThreadPoolExecutor.CallerRunsPolicy())
        );
        log.info("init threadPool {}", cpuPool.size());
    }


    private static class CommandThread implements Callable<CommandResult> {

        private final CpuAffinityCommand cpuAffinityCommand;

        private final Queue<Integer> cpuPool;

        public CommandThread(CpuAffinityCommand cpuAffinityCommand, Queue<Integer> cpuPool) {
            this.cpuAffinityCommand = cpuAffinityCommand;
            this.cpuPool = cpuPool;
        }

        @Override
        public CommandResult<?> call() {
            int cmdHash = System.identityHashCode(cpuAffinityCommand);
            Integer coreNo = null;
            try {
                coreNo = cpuPool.poll();
                log.info("cmd[{}] consume CPU[{}]", cmdHash, coreNo);
                return cpuAffinityCommand.run(coreNo != null ? coreNo : 0);
            } finally {
                log.info("cmd[{}] release CPU[{}]", cmdHash, coreNo);
                if (coreNo != null) {
                    cpuPool.offer(coreNo);
                }
            }
        }
    }
}
