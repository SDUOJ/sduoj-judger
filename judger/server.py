import json
import pika
import os
import time

from judger.exception import *
from judger.lang import LANG_TYPE
from judger.model.checker import checker
from judger.model.client import Judger
from judger.model.handler import JudgerSession
from judger.config import *

import logging, coloredlogs
logger = logging.getLogger(__name__)
coloredlogs.install(level="DEBUG")


class MQHandler(object):
    def __init__(self, mq_host, mq_port, receive_queue, send_queue, session, mq_uname="guest", mq_pwd="guest"):
        self._mq_uname = mq_uname
        self._mq_pwd = mq_pwd
        self._mq_host = mq_host
        self._mq_port = mq_port
        self._receive_queue = receive_queue
        self._send_queue = send_queue
        self.session = session

    def get_channel(self):
        _credentials = pika.PlainCredentials(self._mq_uname, self._mq_pwd)
        _parameters = pika.ConnectionParameters(host=self._mq_host, port=self._mq_port, virtual_host="/sduoj", credentials=_credentials)
        _connection = pika.BlockingConnection(_parameters)
        self.channel = _connection.channel()
    
    def run(self):
        if not hasattr(self, "channel") or self.channel.is_closed:
            self.get_receive_channel()
        # send queue
        # self.send_channel.queue_declare(queue=self._send_queue, durable=True)

        # regist receive queue callback
        self.channel.queue_declare(queue=self._receive_queue, durable=True)
        self.channel.basic_qos(prefetch_count=1)  # limit the number
        self.channel.basic_consume(queue=self._receive_queue, on_message_callback=self.__callback)
        self._session.get_cookies()
        logger.info("Start listening...")
        self.channel.start_consuming()

    def send_checkpoint_result(self, data):
        result_dict = {
            "event": "checkpointOK",
            "data": data,
        }
        print(json.dumps(result_dict, indent=2))
        # self.channel.basic_publish(exchange='', routing_key=self._send_queue, body=json.dumps(result_dict))
    
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
            self.session.update_checkpoints(problem_config["checkpointIds"])
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
                            data_path=BASE_DATA_PATH,
                            # TODO: 改成 checkpointIds
                            input_cases=["%d.in" % checkpointId for checkpointId in problem_config["checkpointIds"]],
                            output_cases=["%d.out" % checkpointId for checkpointId in problem_config["checkpointIds"]],
                            checker=checker,
                            oimode=False,
                            handler=self,
                            )
            result = client.judge()
        except (UserCompileError, SpjCompileError) as e:    # 编译错误
            self.session.send_judge_result(submission_id, 1001, Judger.RETURN_TYPE[Judger.COMPILE_ERROR], 0, 0, 0, str(e))
        except (SpjError, SystemInternalError, SandboxInternalError, HTTPError) as e:  # 系统错误
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
            MQSession(uname=CONFIG["mq_uname"], pwd=CONFIG["mq_pwd"], host=CONFIG["mq_server"], port=CONFIG.get("mq_port", 5672), receive_queue=CONFIG["mq_receive_name"], send_queue=None, handler=session).run()
        except Exception as e:
            # raise e
            print(e)
            pass
        logger.warn("offline from message qeue, retry after {}s".format(RETRY_DELAY_SEC))
        time.sleep(RETRY_DELAY_SEC)


if __name__ == "__main__":
    run()