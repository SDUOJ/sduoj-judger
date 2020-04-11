import json
import pika
import os
import time

from judger.exception import *
from judger.lang import LANG_TYPE
from judger.model.checker import checker
from judger.model.client import Judger
from judger.model.handler import JudgerSession
from judger.config import CONFIG, BASE_WORKSPACE_PATH, BASE_LOG_PATH

import logging, coloredlogs
logger = logging.getLogger(__name__)
coloredlogs.install(level="DEBUG")

RETRY_DELAY_SEC = 30


class MQHandler(object):
    def __init__(self, mq_host, mq_port, queue, session, mq_name="guest", mq_pwd="guest"):
        self._mq_uname = mq_name
        self._mq_pwd = mq_pwd
        self._mq_host = mq_host
        self._mq_port = mq_port
        self._queue = queue
        self.session = session

    def get_receive_channel(self):
        self._credentials = pika.PlainCredentials(self._mq_name, self._mq_pwd)
        self._parameters = pika.ConnectionParameters(host=self._mq_host, port=self._mq_port, virtual_host="/sduoj", credentials=self._credentials)
        self._connection = pika.BlockingConnection(self._parameters)
        self.channel = self._connection.channel()
    
    def run(self):
        if not hasattr(self, "channel") or self.channel.is_closed:
            self.get_receive_channel()
        self.channel.queue_declare(queue=self._queue, durable=True)
        self.channel.basic_qos(prefetch_count=1)  # limit the number
        self.channel.basic_consume(queue=self._queue, on_message_callback=self.__callback)
        self._session.get_cookies()
        logger.info("Start listening...")
        self.channel.start_consuming()

    
    def __callback(self, ch, method, properties, body):
        # ch.basic_ack(delivery_tag=method.delivery_tag)  # manual ack
        request = json.loads(str(body, encoding="utf8"))
        submission_id = int(request["submissionId"])
        logger.info("Get submission request: %d" % submission_id)
        # 查询提交
        submission_config = self.session.submission_query(submission_id)
        submission_code = submission_config["code"]
        # 查看题目时限、数据包地址
        problem_id = submission_config["problemId"]
        problem_config = self.session.problem_query(problem_id)
        try:
            # 检查url是否需要更新
            data_path = self.session.fetch_problem_data(problem_id, problem_config["checkpointIds"])
            # 评测
            client = Judger(submission_id=submission_id,
                            pid=problem_id,
                            code=submission_code,
                            lang=LANG_TYPE[submission_config["data"]["languageId"]],
                            run_config={
                                "max_memory": problem_config["data"]["memoryLimit"] * 1024,
                                "max_cpu_time": problem_config["data"]["timeLimit"],
                                "max_real_time": problem_config["data"]["timeLimit"] * 2,
                            },
                            data_path=os.path.join(data_path, problem_id),
                            # TODO: 改成 checkpointIds
                            input_cases=["input1.txt", "input2.txt", "input3.txt"],
                            output_answers=["output1.txt","output2.txt", "output3.txt"],
                            checker=checker,
                            oimode=False,
                            # handler=self._handler
                            )
            result = client.judge()
        except (UserCompileError, SpjCompileError) as e:    # 编译错误
            self.session.send_judge_result(submission_id, 1001, Judger.RETURN_TYPE[Judger.COMPILE_ERROR], 0, 0, 0, str(e))
        except (SpjError, SystemInternalError, SandboxInternalError) as e:  # 系统错误
            logger.error(str(e))
            self.session.send_judge_result(submission_id, 1001, Judger.RETURN_TYPE[Judger.SYSTEM_ERROR], 0, 0, 0, str(e))
        else:
            # 评测结束 返回结果
            max_result_cpu_time = 0
            max_result_memory = 0
            judge_result = Judger.SUCCESS
            for ret in result["result"].values():
                max_result_cpu_time = max(max_result_cpu_time, ret["cpu_time"])
                max_result_memory = max(max_result_memory, ret["memory"])
                judge_result = ret["result"]
            self.session.send_judge_result(submission_id=submission_id,
                                            judger_id=1001,
                                            judge_result=Judger.RETURN_TYPE[judge_result],
                                            judge_score=0,
                                            used_time=max_result_cpu_time,
                                            used_memory=max_result_memory // 1024,
                                            judger_log="2333")
        finally:
            ch.basic_ack(delivery_tag=method.delivery_tag)  # manual ack

def run():
    try:
        if not os.path.exists(BASE_WORKSPACE_PATH):
            os.mkdir(BASE_WORKSPACE_PATH)
        if not os.path.exists(BASE_LOG_PATH):
            os.mkdir(BASE_LOG_PATH)
        os.chmod(BASE_WORKSPACE_PATH, 0o711)
    except Exception as e:
        print(e)
        # TODO: cannot create workspace, log here
        logger.critical("Crashed while creating WORKSPACE")
        exit(1)

    session = JudgerSession(host=CONFIG["server"], username=CONFIG["uname"], password=CONFIG["pwd"], origin="http://oj.oops.sdu.cn")
    while True:
        try:
            MQSession(uname=CONFIG["mq_uname"], pwd=CONFIG["mq_pwd"], host=CONFIG["mq_server"], port=CONFIG.get("mq_port", 5672), queue=CONFIG["mq_name"], handler=session).run()
        except Exception as e:
            # raise e
            print(e)
            pass
        # TODO: retry, log here
        # logger()
        logger.warn("offline from message qeue, retry after {}s".format(RETRY_DELAY_SEC))
        time.sleep(RETRY_DELAY_SEC)


if __name__ == "__main__":
    run()