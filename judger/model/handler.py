import datetime, time
import json
import requests
import hashlib
import shutil
import os
import zipfile
from judger.config import *
from urllib.parse import urljoin
from judger.exception import HTTPError

import logging, coloredlogs
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.NOTSET)
coloredlogs.install(level="DEBUG")


RETRY_DELAY_SEC = 5


def resolve_response(response):
    if response.status_code != 200: raise HTTPError("unexpected http code " + response.status_code)
    response_dict = response.json()
    code = response_dict["code"]
    message = response_dict['message']
    logger.debug("code: {}\nmessage: {}".format(code, json.dumps(message, indent=4)))
    if code != 0: raise HTTPError("code: {}\nmessage: {}".format(code, message))
    return response_dict["data"]

class JudgerSession(object):
    def __init__(self, host, username, password, origin):
        self.host = host
        self.__username = username
        self.__password = password
        self.__headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
            "Origin": origin,
        }
        self.__cookies = requests.cookies.RequestsCookieJar()

    def full_url(self, *parts):
        return urljoin(self.host, os.path.join(*parts))
    
    def post_json(self, url, data, update_cookies=False):
        response = requests.post(self.full_url(url), headers=self.__headers, data=data, cookies=self.__cookies, allow_redirect=False)
        if update_cookies:
            self.cookies.update(response.cookies)
            for item in response.headers["Set-Cookie"].split("; "):
                if item.split("=")[0] == "Expires":
                    self.cookies_expires = datetime.datetime.strptime(item.split("=")[1], "%a, %d-%b-%Y %H:%M:%S %Z")
        return resolve_response(response)

    def check_cookies_expires(self):
        while datetime.datetime.now() > self.cookies_expires:
            logger.error("Session is out of date")
            if not self.get_cookies():
                logger.warn("retry after {}s".format(RETRY_DELAY_SEC))
                time.sleep(RETRY_DELAY_SEC)
            else:
                logger.info("Connected")

    def get_cookies(self):
        data = {
            "username": str(self.username),
            "password": str(self.password),
        }
        try:
            self.post_json("/api/judger/auth/login", data, update_cookies=True)
        except Exception:
            return False
        else:
            return True

    def submission_query(self, submission_id):
        self.check_cookies_expires()
        data = {
            "submissionId": int(submission_id)
        }
        return self.post_json("/api/judger/submit/query", data)

    def problem_query(self, pid):
        self.check_cookies_expires()
        data = {
            "problemId": int(pid, base=10)
        }
        return self.post_json("/api/judger/problem/query", data)

    def send_judge_result(self, submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log):
        self.check_cookies_expires()
        data = {
            "submissionId": int(submission_id),
            "judgerId": int(judger_id),
            "judgeResult": int(judge_result),
            "judgeScore": int(judge_score),
            "usedTime": int(used_time),
            "usedMemory": int(used_memory),
            "judgeLog": str(judger_log),
        }
        self.post_json("/api/judger/submit/update", data)

    # TODO: 获取数据点逻辑修改,该函数需要重构
    def fetch_problem_data(self, problem_id, url):
        problem_md5 = url.strip("/").split("/")[-1]
        data_path = "{}-{}".format(problem_id, problem_md5)
        full_data_path = os.path.join(BASE_DATA_PATH, data_path + ".zip")

        if os.path.exists(full_data_path):
            return data_path
        
        logger.info("Fetching problem data: \"{}\"".format(full_data_path))
        for _dir in os.listdir(BASE_DATA_PATH):
            if _dir.startswith("%s-" % problem_id):
                shutil.rmtree(os.path.join(BASE_DATA_PATH, _dir))

        
        
        with requests.get(url, cookies=self.cookies) as response:
            # if hasattr(response, content_type) and response.content_type == "application/json":
            #     response_dict = response.json()
            #     # TODO: expect file but get json here, log it
            #     raise Exception()

            if response.status_code != 200:
                # TODO: non 200 ret code, log it
                raise ValueError("http code: {}".format(response.status_code))
            
            with open(full_data_path, "wb") as f:
                f.write(response.content)
            
        with open(full_data_path, "rb") as f:
            md5obj = hashlib.md5()
            md5obj.update(f.read())
            _hash = md5obj.hexdigest()

            if str(_hash) != problem_md5:
                # TODO: unmatch md5, log here
                logger.error("Unmatched MD5: \"{}\"".format(full_data_path))
                raise ValueError("Unmatched MD5")

        with zipfile.ZipFile(full_data_path, "r") as f:
            f.extractall(os.path.join(BASE_DATA_PATH, data_path))
        os.unlink(full_data_path)
        return data_path