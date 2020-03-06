import json


class Fetcher:

    @staticmethod
    def FetchStr():
        # API -> SQL
        code = open("file/test_common.cc", "r+").read()
        js = {
            "submission_id": 998244353,
            "code": code,
            "pid": 1002,
            "lang": "cc",
            "run_config": {
                    "max_memory": 16 * 1024 * 1024,
                    "max_cpu_time": 1000,
                    "max_real_time": 1000,
            },
            "spj": {
                "src_path": "data/1002/spj/spj.cc",
                "lang": "cc",
            }
        }
        return json.dumps(js)

# 题目表：时间限制、空间限制、题号
# 提交表：submision_id、代码、题号、提交形式（OI-给出分数、ACM）、语言
