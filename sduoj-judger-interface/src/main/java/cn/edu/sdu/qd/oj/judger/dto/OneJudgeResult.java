package cn.edu.sdu.qd.oj.judger.dto;


import java.util.ArrayList;

public class OneJudgeResult extends ArrayList<Object> {

    public static final int INDEX_SUBMISSION_ID = 0;
    public static final int INDEX_CHECKPOINT_INDEX = 1;
    public static final int INDEX_JUDGE_RESULT = 2;
    public static final int INDEX_JUDGE_SCORE = 3;
    public static final int INDEX_USED_TIME = 4;
    public static final int INDEX_USED_MEMORY = 5;

    public OneJudgeResult(Long submisionId) {
        super(2);
        add(INDEX_SUBMISSION_ID, String.valueOf(submisionId));
        add(-1);
    }

    public OneJudgeResult(Long submisionId, Integer checkpintIndex, Integer judgeResult, Integer judgeScore, Integer usedTime, Integer usedMemory) {
        super(6);
        add(INDEX_SUBMISSION_ID, String.valueOf(submisionId));
        add(INDEX_CHECKPOINT_INDEX, checkpintIndex);
        add(INDEX_JUDGE_RESULT, judgeResult);
        add(INDEX_JUDGE_SCORE, judgeScore);
        add(INDEX_USED_TIME, usedTime);
        add(INDEX_USED_MEMORY, usedMemory);
    }
}
