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

    @Value("${sduoj.judger.coreNum}")
    private int coreNum;

    // CPU 池
    private final Queue<Integer> cpuPool;

    // 线程池
    private final CompletionService<CommandExecuteResult> threadPool;


    public void submit(Command command) {
        threadPool.submit(new CommandThread(command));
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
                new ThreadPoolExecutor.CallerRunsPolicy()) {

            protected void beforeExecute(Thread t, Runnable r) {
                Integer coreNo = cpuPool.poll();
                log.info("consume {}", coreNo);
                ((CommandThread) r).setCoreNo(coreNo);
            }

            protected void afterExecute(Thread t, Runnable r) {
                int coreNo = ((CommandThread) r).getCoreNo();
                log.info("release {}", coreNo);
                cpuPool.offer(coreNo);
            }
        });
        log.info("init threadPool {}", coreNum);
    }


    private static class CommandThread implements Callable<CommandExecuteResult> {

        private int coreNo;

        private final Command command;

        public CommandThread(Command command) {
            this.command = command;
        }

        public void setCoreNo(Integer coreNo) {
            this.coreNo = coreNo == null ? 0 : coreNo;
        }

        public int getCoreNo() {
            int tmp = coreNo;
            this.coreNo = 0;
            return tmp;
        }

        @Override
        public CommandExecuteResult call() throws Exception {
            log.info("exec {}", command.toString());
            return command.run(coreNo);
        }
    }
}
