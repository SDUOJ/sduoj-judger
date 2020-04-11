import json
import sys
import os
import shutil

# sys.path.append('../src')
from judger.model.client import Judger
from judger.config import BASE_LOG_PATH, BASE_WORKSPACE_PATH
from judger.server import checker
from judger.exception import *


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
    # indx = input()
    code = open("test/file/test_common.cc", "r+").read()
    js = {
        "submission_id": 1,
        "code": code,
        "pid": 1003,
        "lang": "cc",
        "run_config": {
                "max_memory": 500 * 1024 * 1024,
                "max_cpu_time": 24000,
                "max_real_time": 24000,
        },
    }
    # print(js)

    if not os.path.exists(BASE_WORKSPACE_PATH):
        os.mkdir(BASE_WORKSPACE_PATH)
    if not os.path.exists(BASE_LOG_PATH):
        os.mkdir(BASE_LOG_PATH)
    os.chmod(BASE_WORKSPACE_PATH, 0o711)
    try:
        client = Judger(submission_id=js["submission_id"],
                        pid=js["pid"],
                        code=js["code"],
                        lang=js["lang"],
                        run_config=js["run_config"],
                        data_path="1003",
                        input_cases=["%d.in" % i for i in range(1, 11)],
                        output_answers=["%d.out" % i for i in range(1, 11)],
                        checker=checker,
                        oimode=True,)
        result = client.judge()
    except Exception as e:
        raise
        print(type(e))
        print(e)
    else:
        print(result)

    # shutil.rmtree(BASE_WORKSPACE_PATH)
