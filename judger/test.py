import json
import sys
import os
import shutil
from judger.model.client import Judger
from judger.model.checker import checker
from judger.exception import *
from judger.server import MQHandler
from judger.config import BASE_LOG_PATH, BASE_WORKSPACE_PATH, BASE_DATA_PATH


if __name__ == "__main__":
    code = open("test/file/test_common.cc", "r+").read()
    config = {
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
    handler = MQHandler(None, None, None, None, None)
    if not os.path.exists(BASE_WORKSPACE_PATH):
        os.mkdir(BASE_WORKSPACE_PATH)
    if not os.path.exists(BASE_LOG_PATH):
        os.mkdir(BASE_LOG_PATH)
    os.chmod(BASE_WORKSPACE_PATH, 0o711)
    try:
        client = Judger(submission_id=config["submission_id"],
                        pid=config["pid"],
                        code=config["code"],
                        lang=config["lang"],
                        run_config=config["run_config"],
                        data_path=BASE_DATA_PATH,
                        input_cases=["%d.in" % i for i in range(1, 11)],
                        output_answers=["%d.out" % i for i in range(1, 11)],
                        checker=checker,
                        oimode=True,
                        handler=handler,
                        )
        result = client.judge()
    except Exception as e:
        raise
        print(type(e))
        print(e)
    else:
        print(json.dumps(result, indent=2))

    shutil.rmtree(BASE_WORKSPACE_PATH)
