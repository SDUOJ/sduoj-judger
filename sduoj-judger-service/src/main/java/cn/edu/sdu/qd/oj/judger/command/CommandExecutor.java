/*
 * Copyright 2020-2021 the original author or authors.
 *
 * Licensed under the General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/gpl-3.0.en.html
 */

package cn.edu.sdu.qd.oj.judger.command;

import cn.edu.sdu.qd.oj.judger.config.CpuConfig;
import cn.edu.sdu.qd.oj.judger.dto.CommandExecuteResult;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Queue;
import java.util.concurrent.*;

/**
 * @Description 单核命令行执行者的调度器和管理器
 **/

@Slf4j
@Component
public class CommandExecutor {

    // CPU 池
    private final Queue<Integer> cpuPool;

    // 线程池
    private final CompletionService<CommandExecuteResult> threadPool;

    /**
     * @Description 提交一个异步任务
     **/
    public void submit(Command command) {
        threadPool.submit(new CommandThread(command, cpuPool));
    }

    /**
     * @Description 获取一个任务的执行结果，顺序任意取决于任务完成顺序
     * @return cn.edu.sdu.qd.oj.judger.dto.CommandExecResult
     **/
    public CommandExecuteResult take() throws InterruptedException, ExecutionException {
        return threadPool.take().get();
    }

    public CommandExecutor() {
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


    private static class CommandThread implements Callable<CommandExecuteResult> {

        private final Command command;

        private final Queue<Integer> cpuPool;

        public CommandThread(Command command, Queue<Integer> cpuPool) {
            this.command = command;
            this.cpuPool = cpuPool;
        }

        @Override
        public CommandExecuteResult call() throws Exception {
            log.info("exec {}", command.toString());
            Integer coreNo = null;
            try {
                coreNo = cpuPool.poll();
                log.info("cpu consume {}", coreNo);
                return command.run(coreNo != null ? coreNo : 0);
            } finally {
                log.info("cpu release {}", coreNo);
                if (coreNo != null) {
                    cpuPool.offer(coreNo);
                }
            }
        }
    }
}
