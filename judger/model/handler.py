import datetime, time
import json
import requests
import hashlib
import shutil
import os
import zipfile
from judger.config import *

class RequestHandler(object):
    
    def __init__(self, host, username, password):
        self.host = host
        self.username = username
        self.password = password
        self.headers = {
            "Content-Type": "application/json",
            "Origin": "http://oj.oops-sdu.cn"
        }
        self.cookies = requests.cookies.RequestsCookieJar()

    def check_cookies_expires(self):
        while datetime.datetime.now() > self.cookies_expires:
            self.get_cookies()

    def get_cookies(self):
        data = {
            "username": str(self.username),
            "password": str(self.password),
        }
        response = requests.post(self.host + "/api/auth/login", headers=self.headers, data=json.dumps(data))
        
        self.cookies.update(response.cookies)
        for item in response.headers["Set-Cookie"].split("; "):
            if item.split("=")[0] == "Expires":
                self.cookies_expires = datetime.datetime.strptime(item.split("=")[1], "%a, %d-%b-%Y %H:%M:%S %Z")
        
        return response.status_code == 200 and json.loads(response.text)["code"] == 0
        

    def submission_query(self, submission_id):
        self.check_cookies_expires()
        data = {
            "id": submission_id
        }
        response = requests.post(self.host + "/api/submit/querybyjudger", headers=self.headers, data=json.dumps(data), cookies=self.cookies)

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
            "id": pid
        }
        response = requests.post(self.host + "/api/problem/querybyjudger", headers=self.headers, data=json.dumps(data), cookies=self.cookies)
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
            "id": submission_id,
            "judgeId": judger_id,
            "judgeResult": judge_result,
            "judgeScore": judge_score,
            "usedTime": used_time,
            "usedMemory": used_memory,
            "judgeLog": judger_log
        }
        print(data)
        response = requests.post(self.host + "/api/submit/update", headers=self.headers, data=json.dumps(data), cookies=self.cookies)
        return response.status_code == 200 and json.loads(response.text)["code"] == 0

    def fetch_problem_data(self, problem_id, url):
        problem_md5 = url.strip("/").split("/")[-1]
        data_path = "{}-{}".format(problem_id, problem_md5)
        full_data_path = os.path.join(BASE_DATA_PATH, data_path + ".zip")

        if os.path.exists(full_data_path):
            return data_path
        
        for _dir in os.listdir(BASE_DATA_PATH):
            if _dir.startswith("%s-" % problem_id):
                shutil.rmtree(os.path.join(BASE_DATA_PATH, _dir)) 
        
        print("Fetch problem data: %s %s" % (problem_id, url))
        with requests.get(url, cookies=self.cookies) as response:
            # if hasattr(response, content_type) and response.content_type == "application/json":
            #     response_dict = response.json()
            #     # TODO: expect file but get json here, log it
            #     raise Exception()

            if response.status_code != 200:
                # TODO: non 200 ret code, log it
                raise Exception()
            
            with open(full_data_path, "wb") as f:
                f.write(response.content)
            
        with open(full_data_path, "rb") as f:
            md5obj = hashlib.md5()
            md5obj.update(f.read())
            _hash = md5obj.hexdigest()

            if str(_hash) != problem_md5:
                # TODO: unmatch md5, log here
                raise Exception()

        with zipfile.ZipFile(full_data_path, "r") as f:
            f.extractall(os.path.join(BASE_DATA_PATH, data_path))
        os.unlink(full_data_path)
        return data_path


    @staticmethod
    def __send_one_judge_result(submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log):
        RequestHandler().send_judge_result(submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log)