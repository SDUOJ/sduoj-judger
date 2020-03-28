import json
import pika
import os
import time

from judger.lang import LANG_TYPE
from judger.model.client import Judger
from judger.model.handler import RequestHandler
from judger.config import CONFIG, BASE_WORKSPACE_PATH, BASE_LOG_PATH

RETRY_DELAY_SEC = 30

def checker(test_output, std_output):
    import difflib
    import subprocess
    command = "diff {} {}".format(std_output, test_output)
    if subprocess.getstatusoutput(command)[0]:
        command += " --ignore-space-change --ignore-blank-lines"
        return Judger.WRONG_ANSWER if subprocess.getstatusoutput(command)[0] else Judger.PRESENTATION_ERROR
    return Judger.SUCCESS


class ReceiverClient(object):
    def __init__(self, host, port, queue, handler, uname=None, pwd=None):
        self._uname = uname
        self._pwd = pwd
        self._host = host
        self._port = port
        self._queue = queue
        self._handler = handler

    def get_channel(self):
        if self._uname and self._pwd:
            self._credentials = pika.PlainCredentials(self._uname, self._pwd)
        else:
            self._credentials = pika.PlainCredentials("guest", "guest")
        self._parameters = pika.ConnectionParameters(host=self._host, port=self._port, virtual_host="/sduoj", credentials=self._credentials)
        self._connection = pika.BlockingConnection(self._parameters)
        self.channel = self._connection.channel()
    
    def run(self):
        if not hasattr(self, "channel") or self.channel.is_closed:
            self.get_channel()
        self.channel.queue_declare(queue=self._queue, durable=True)
        self.channel.basic_qos(prefetch_count=1)  # limit the number
        self.channel.basic_consume(queue=self._queue, on_message_callback=self._callback)
        print("[*] Start consuming...")
        self._handler.get_cookies()
        self.channel.start_consuming()

    
    def _callback(self, ch, method, properties, body):
        # ch.basic_ack(delivery_tag=method.delivery_tag)  # manual ack
        tmp = json.loads(str(body, encoding="utf8"))
        submission_id = int(tmp["submissionId"])
        print(submission_id)
        # 查询提交
        submission_config = self._handler.submission_query(submission_id)
        print(submission_config)
        # code 用 base64 加密传输
        submission_code = submission_config["data"]["code"]
        # submission_code = str(base64.b64decode(submission_config["data"]["code"]), encoding="utf-8")
        # 查看题目时限、数据包地址
        problem_id = submission_config["data"]["problemId"]
        problem_config = self._handler.problem_query(problem_id)
        print(problem_id, problem_config)
        # 检查url是否需要更新
        # TODO
        data_path = self._handler.fetch_problem_data(problem_id, problem_config["data"]["checkpointUrl"])
        # 评测
        try:
            client = Judger(submission_id=submission_id,
                            pid=problem_id,
                            code=submission_code,
                            lang=LANG_TYPE[submission_config["data"]["languageId"]],
                            run_config={
                                "max_memory": problem_config["data"]["memoryLimit"] * 1024,
                                "max_cpu_time": problem_config["data"]["timeLimit"],
                                "max_real_time": problem_config["data"]["timeLimit"] * 2,
                            },
                            data_path=data_path+"/1001",
                            input_cases=["input1.txt", "input2.txt", "input3.txt"],
                            output_answers=["output1.txt","output2.txt", "output3.txt"],
                            checker=checker,
                            oimode=False,
                            # handler=self._handler
                            )
            result = client.judge()
        except UserCompileError as e:
            self._handler.send_judge_result(
                submission_id, e.where(), "Compile Error", 0, 0, 0, str(e))
        except SpjCompileError as e:
            self._handler.send_judge_result(
                submission_id, e.where(), "Special Judge Compile Error", 0, 0, 0, str(e))
        except SpjError as e:
            self._handler.send_judge_result(
                submission_id, e.where(), "Special Judge Error", 0, 0, 0, str(e))
        except SystemInternalError as e:
            self._handler.send_judge_result(
                submission_id, e.where(), "System Internal Error", 0, 0, 0, str(e))
        except SandboxInternalError as e:
            self._handler.send_judge_result(
                submission_id, e.where(), "Sandbox Internal Error", 0, 0, 0, str(e))
        else:
            # 传送结果
            print(result)
            max_result_cpu_time = 0
            max_result_memory = 0
            judge_result = Judger.SUCCESS
            for ret in result["result"].values():
                max_result_cpu_time = max(max_result_cpu_time, ret["cpu_time"])
                max_result_memory = max(max_result_memory, ret["memory"])
                judge_result = ret["result"]
            self._handler.send_judge_result(submission_id=submission_id,
                                            judger_id=1001,
                                            judge_result=Judger.RETURN_TYPE[judge_result],
                                            judge_score=0,
                                            used_time=max_result_cpu_time,
                                            used_memory=max_result_memory // 1024,
                                            judger_log="2333")

        ch.basic_ack(delivery_tag=method.delivery_tag)  # manual ack

def run():
    try:
        if not os.path.exists(BASE_WORKSPACE_PATH):
            os.mkdir(BASE_WORKSPACE_PATH)
        if not os.path.exists(BASE_LOG_PATH):
            os.mkdir(BASE_LOG_PATH)
    except Exception as e:
        print(e)
        # TODO: cannot create workspace, log here
        exit(1)

    handler = RequestHandler(host=CONFIG["server"], username=CONFIG["uname"], password=CONFIG["pwd"])
    while True:
        try:
            ReceiverClient(uname=CONFIG["mq_uname"], pwd=CONFIG["mq_pwd"], host=CONFIG["mq_server"], port=CONFIG.get("mq_port", 5672), queue=CONFIG["mq_name"], handler=handler).run()
        except Exception as e:
            raise e
            print(e)
            pass
        # TODO: retry, log here
        print("Retry after %ds" % RETRY_DELAY_SEC)
        time.sleep(RETRY_DELAY_SEC)


if __name__ == "__main__":
    run()