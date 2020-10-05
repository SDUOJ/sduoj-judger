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
        raise HTTPError("unexpected http code " + str(response.status_code))
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
            "Origin": origin,
        }
        self.__cookies = requests.cookies.RequestsCookieJar()

    def full_url(self, *parts):
        return urljoin(self.host, os.path.join(*parts))

    def get_json(self, url, data, expected_type="application/json"):
        print(self.full_url(url), data, self.__cookies.values)
        response = requests.get(self.full_url(url), headers=self.__headers, params=data, cookies=self.__cookies)
        print(response.status_code, response.headers, response.text)
        if expected_type not in response.headers["content-type"]:
            raise HTTPError("unexpected content type " + response.headers["content-type"])
        if expected_type != "application/json":
            return response
        return resolve_response_json(response)

    def post_json(self, url, data, update_cookies=False, expected_type="application/json"):
        print(self.full_url(url), data)
        response = requests.post(self.full_url(url), headers=self.__headers, data=json.dumps(data), cookies=self.__cookies)
        print(response.status_code, response.headers)
        if expected_type not in response.headers["content-type"]:
            raise HTTPError("unexpected content type " + response.headers["content-type"])
        if expected_type != "application/json":
            return response
        if update_cookies:
            self.__cookies = response.cookies
        return resolve_response_json(response)

    def get_cookies(self):
        data = {
            "username": str(self.__username),
            "password": str(self.__password),
        }
        try:
            self.post_json("/api/user/login", data, update_cookies=True)
        except Exception as e:
            raise e
            return False
        else:
            return True

    def submission_query(self, submission_id):
        data = {
            "submissionId": submission_id
        }
        return self.get_json("/api/judger/submit/query", data)

    def problem_query(self, pid):
        data = {
            "problemId": int(pid)
        }
        return self.get_json("/api/judger/problem/query", data)

    def send_judge_result(self, submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log, checkpointResults):
        data = {
            "submissionId": submission_id,
            "judgeResult": int(judge_result),
            "judgeScore": int(judge_score),
            "usedTime": int(used_time),
            "usedMemory": int(used_memory),
            "judgeLog": str(judger_log),
            "checkpointResults": checkpointResults
        }
        self.post_json("/api/judger/submit/update", data)

    def update_checkpoints(self, checkpointIds, retry=3):
        needed_checkpointids = [str(checkpointId) for checkpointId in checkpointIds if checkpointId not in CHECKPOINTIDS]
        if not needed_checkpointids:
            return
        for _ in range(retry):
            try:
                data = self.post_json("/api/judger/checkpoint/download", needed_checkpointids, expected_type="application/zip")
            except Exception as e:
                logging.error(str(e))
                continue
            else:
                with zipfile.ZipFile(file=BytesIO(data.content)) as f:
                    f.extractall(BASE_DATA_PATH)
                    for checkpointId in needed_checkpointids:
                        CHECKPOINTIDS[checkpointId] = True
                return
        raise HTTPError("update checkpoints failed")
