package cn.edu.sdu.qd.oj.judger.command;

import cn.edu.sdu.qd.oj.judger.dto.CommandExecuteResult;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
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

    public CommandExecutor(@Value("${sduoj.judger.core-num}") int coreNum) {
        // 初始化 cpu 池
        cpuPool = new LinkedBlockingDeque<>(coreNum);
        for (int i = 0; i < coreNum; i++) {
            cpuPool.offer(i);
        }
        // 初始化线程池
        threadPool = new ExecutorCompletionService<>(new ThreadPoolExecutor(
                coreNum,
                coreNum,
                0,
                TimeUnit.SECONDS,
                new LinkedBlockingQueue<>(1024),
                new ThreadPoolExecutor.CallerRunsPolicy())
        );
        log.info("init threadPool {}", coreNum);
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
