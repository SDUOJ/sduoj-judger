import pika
import os
from judger.model.handler import RequestHandler
from judger.server.server import ReceiverClient
from judger.config import CONFIG, BASE_WORKSPACE_PATH, BASE_LOG_PATH
RETRY_DELAY_SEC = 30

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
            ReceiverClient(uname=CONFIG["mq_uname"], pwd=CONFIG["mq_pwd"], host=CONFIG["mq_server"], port=CONFIG.get("mq_port", 5672), handler=handler).run()
        except Exception as e:
            print(e)
            pass
        # TODO: retry, log here
        sleep(RETRY_DELAY_SEC)


if __name__ == "__main__":
    run()