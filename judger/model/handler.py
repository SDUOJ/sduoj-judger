import datetime, time
import json
import requests

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
        response = requests.post(self.host + "/api/submit/querybyjudger", headers=self.headers, data=json.dumps(data), cookies = self.cookies)
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
        response = requests.post(self.host + "/api/problem/querybyjudger", headers=self.headers, data=json.dumps(data), cookies = self.cookies)
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
        response = requests.post(self.host + "/api/submit/update", headers=self.headers, data=json.dumps(data), cookies = self.cookies)
        return response.status_code == 200 and json.loads(response.text)["code"] == 0

    @staticmethod
    def __send_one_judge_result(submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log):
        RequestHandler().send_judge_result(submission_id, judger_id, judge_result, judge_score, used_time, used_memory, judger_log)

        
def main():
    tmp = RequestHandler("http://api.oj.xrvitd.com:8080","tttt","111")
    print(tmp.get_cookies())


if __name__ == "__main__":
    main()