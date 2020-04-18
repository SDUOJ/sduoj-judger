import datetime, time
import json
import requests
import hashlib
import shutil
import os
import zipfile
from io import BytesIO
from urllib.parse import urljoin
from judger.config import *
from judger.exception import HTTPError

import logging, coloredlogs
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.NOTSET)
coloredlogs.install(level="DEBUG")


def resolve_response_json(response):
    if response.status_code != 200: 
        raise HTTPError("unexpected http code " + response.status_code)
    response_dict = response.json()
    code = response_dict["code"]
    message = response_dict['message']
    logger.debug("code: {}\nmessage: {}".format(code, json.dumps(message, indent=4)))
    if code != 0: 
        raise HTTPError("code: {}\nmessage: {}".format(code, message))
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
    
    def post_json(self, url, data, update_cookies=False, expected_type="application/json"):
        response = requests.post(self.full_url(url), headers=self.__headers, data=data, cookies=self.__cookies, allow_redirect=False)
        if response.content_type != expected_type:
            raise HTTPError("unexpected content type " + response.content_type)
        if expected_type != "application/json":
            return response
        if update_cookies:
            self.cookies.update(response.cookies)
            for item in response.headers["Set-Cookie"].split("; "):
                if item.split("=")[0] == "Expires":
                    self.cookies_expires = datetime.datetime.strptime(item.split("=")[1], "%a, %d-%b-%Y %H:%M:%S %Z")
        return resolve_response_json(response)

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

    def update_checkpoints(self, checkpointIds, retry=3):
        needed_checkpointids = [checkpointId for checkpointId in checkpointIds if checkpointId not in CHECKPOINTIDS]
        for _ in range(retry):
            try:
                data = self.post_json("/api/judger/checkpoint/download", {"checkpointIds": needed_checkpointids}, "application/octet-stream")
            except Exception as e:
                logging.warn(str(e))
                continue
            else:
                with zipfile.ZipFile(file=BytesIO(data)) as f:
                    f.extractall(BASE_DATA_PATH)
                for checkpointId in needed_checkpointids:
                    CHECKPOINTIDS[checkpointId] = True
                break
        raise HTTPError("update checkpoints failed, retried for %d times" % retry)
