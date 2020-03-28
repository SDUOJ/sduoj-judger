import json
import pika
import base64
from judger.exception import *
from judger.lang import LANG_TYPE
from judger.model.handler import *
from judger.model.client import Judger


def __checker(test_output, std_output):
    import difflib
    import subprocess
    command = "diff {} {}".format(std_output, test_output)
    if subprocess.getstatusoutput(command)[0]:
        command += " --ignore-space-change --ignore-blank-lines"
        return Judger.WRONG_ANSWER if subprocess.getstatusoutput(command)[0] else Judger.PRESENTATION_ERROR
    return Judger.SUCCESS


class ReceiverClient(object):
    def __init__(self, host, port, handler, uname=None, pwd=None):
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
        
        self._parameters = pika.ConnectionParameters(host=self._host, port=self._port, credentials=self._credentials)
        self._connection = pika.BlockingConnection(self._parameters)
        self.channel = self._connection.channel()
    
    def run(self):
        if not hasattr(self, "channel") or self.channel.is_closed:
            self.get_channel()
        self.channel.queue_declare(queue=self._queue, durable=True)
        self.channel.basic_qos(prefetch_count=1)  # limit the number
        self.channel.basic_consume(queue=self._queue, on_message_callback=self._callback)
        print("[*] Start consuming...")
        self.channel.start_consuming()
    
    def _callback(self, ch, method, properties, body):
        submission_id = int(str(body, encoding="utf-8"))
        # 查询提交
        submission_config = handler.submission_query(submission_id)
        # code 用 base64 加密传输
        submission_code = str(base64.b64decode(
            submission_config["data"]["code"]), encoding="utf-8")
        # 查看题目时限、数据包地址
        problem_id = submission_config["data"]["problemId"]
        problem_config = handler.problem_query(problem_id)
        # 检查url是否需要更新
        # TODO
        # 评测
        try:
            client = Judger(submission_id=submission_id,
                            pid=problem_id,
                            code=submission_code,
                            lang=LANG_TYPE[submission_config["data"]
                                        ["languageId"]],
                            run_config={
                                "max_memory": problem_config["data"]["memoryLimit"],
                                "max_cpu_time": problem_config["data"]["timeLimit"],
                                "max_real_time": problem_config["data"]["timeLimit"] * 2,
                            },
                            input_path="test/data/{}/input".format(problem_id),
                            input_cases=["input1.txt", "input2.txt", "input3.txt"],
                            answer_path="test/data/{}/output".format(problem_id),
                            output_answers=["output1.txt",
                                            "output2.txt", "output3.txt"],
                            checker=__checker,
                            oimode=True,
                            handler=self._handler
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
        # else:
        #     # 传送结果
        #     result1 = result["result"]["input1.txt"]
        #     handler.send_judge_result(
        #         submission_id, 0, Judger.RETURN_TYPE[result1["result"]], 10, result1["cpu_time"], result1["memory"], "")
        #     print(result)

        ch.basic_ack(delivery_tag=method.delivery_tag)  # manual ack

