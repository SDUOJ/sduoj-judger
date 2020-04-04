import datetime, time
import json
import requests
import hashlib
import shutil
import os
import zipfile
from judger.config import *
from urllib.parse import urljoin

import logging, coloredlogs
logger = logging.getLogger(__name__)
coloredlogs.install(level="DEBUG")

DELAY = 30

class Session(object):
    def __init__(self, host, username, password, origin):
        self.host = host
        self.username = username
        self.password = password
        self.headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
            "Origin": origin,
        }
        self.cookies = requests.cookies.RequestsCookieJar()

    def full_url(self, *parts):
        return urljoin(self.host, os.path.join(*parts))

    def check_cookies_expires(self):
        while datetime.datetime.now() > self.cookies_expires:
            logger.error("session out of date")
            if not self.get_cookies():
                logger.warn("retry after {}s".format(DELAY))
                time.sleep(DELAY)
            else:
                logger.info("Connected")

    def get_cookies(self):
        data = {
            "username": str(self.username),
            "password": str(self.password),
        }
        response = requests.post(self.full_url("/api/auth/judger/login"), headers=self.headers, data=json.dumps(data))
        
        self.cookies.update(response.cookies)
        for item in response.headers["Set-Cookie"].split("; "):
            if item.split("=")[0] == "Expires":
                self.cookies_expires = datetime.datetime.strptime(item.split("=")[1], "%a, %d-%b-%Y %H:%M:%S %Z")
        
        return response.status_code == 200 and json.loads(response.text)["code"] == 0
        

    def submission_query(self, submission_id):
        self.check_cookies_expires()
        data = {
            "submissionId": int(submission_id, base=10)
        }
        response = requests.post(self.full_url("/api/submit/judger/query"), headers=self.headers, data=json.dumps(data), cookies=self.cookies)

        if response.status_code != 200:
            # TODO: log here
            return
        ret = json.loads(response.text)
        if ret["code"]:
            # TODO: log here
            return
        return ret

    def problem_query(self, pid):
        self.check_cookies_expires()
        data = {
            "problemId": int(pid, base=10)
        }
        response = requests.post(self.full_url("/api/problem/judger/query"), headers=self.headers, data=json.dumps(data), cookies=self.cookies)
        if response.status_code != 200:
            # TODO: log here
            return
        ret = json.loads(response.text)
        if ret["code"]:
            # TODO: log here
            return
        return ret

    def send_judge_result(self, submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log):
        self.check_cookies_expires()
        data = {
            "submissionId": int(submission_id, base=10),
            "judgerId": int(judger_id, base=10),
            "judgeResult": str(judge_result),
            "judgeScore": int(judge_score, base=10),
            "usedTime": int(used_time, base=10),
            "usedMemory": int(used_memory, base=10),
            "judgeLog": str(judger_log),
        }
        logger.info(data)
        response = requests.post(self.full_url("/api/submit/judger/update"), headers=self.headers, data=json.dumps(data), cookies=self.cookies)
        logger.info(response.status_code)
        return response.status_code == 200 and json.loads(response.text)["code"] == 0

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


    def send_one_judge_result(self, submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log):
        self.send_judge_result(submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log)