package cn.edu.sdu.qd.oj.judger.command;

import cn.edu.sdu.qd.oj.judger.dto.CommandExecuteResult;

public interface Command {
    CommandExecuteResult run(int coreNo);
}
