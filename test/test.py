import json
import sys
import os

sys.path.append('../src')
from judger import *
from config import BASE_LOG_PATH, BASE_WORKSPACE_PATH


# 题目表：时间限制、空间限制、题号
# 提交表：submision_id、代码、题号、提交形式（OI-给出分数、ACM）、语言

def __checker(test_output, std_output):
    import difflib
    command = "diff {} {}".format(std_output, test_output)
    if subprocess.getstatusoutput(command)[0]:
        command += " --ignore-space-change --ignore-blank-lines"
        return Judger.WRONG_ANSWER if subprocess.getstatusoutput(command)[0] else Judger.PRESENTATION_ERROR
    return Judger.SUCCESS


if __name__ == "__main__":
    # API -> SQL
    code = open("file/test_spj.cc", "r+").read()
    js = {
        "submission_id": 998244353,
        "code": code,
        "pid": 1001,
        "lang": "cc",
        "run_config": {
                "max_memory": 16 * 1024 * 1024,
                "max_cpu_time": 1000,
                "max_real_time": 1000,
        },
        "spj": {
            "src_path": "data/1002/spj/spj.cc",
            "exe_path": "data/1002/spj/spj",
            "lang": "cc",
        }
    }
    # print(js)

    if not os.path.exists(BASE_WORKSPACE_PATH):
        os.mkdir(BASE_WORKSPACE_PATH)
    if not os.path.exists(BASE_LOG_PATH):
        os.mkdir(BASE_LOG_PATH)

    client = Judger(submission_id=js["submission_id"],
                    pid=js["pid"],
                    code=js["code"],
                    lang=js["lang"],
                    run_config=js["run_config"],
                    input_path="data/{}/input".format(js["pid"]),
                    input_cases=["input1.txt", "input2.txt", "input3.txt"],
                    answer_path="data/{}/output".format(js["pid"]),
                    output_answers=["output1.txt",
                                    "output2.txt", "output3.txt"],
                    # checker=__checker,
                    spj=js["spj"],
                    oimode=True,
                    )
    result = client.judge()
    print(result)
