import requests
import json

judger_id = 1

class RequestHandler(object):
    
    def submission_query(self, submission_id):
        headers = {
            # "Content-Type": "application/json",
            "Origin": "http://oj.oops-sdu.cn",
        }

        data = {
            "id": submission_id
        }

        response = requests.post("https://mockapi.eolinker.com/mS5uWHX6f6afa5576ac65e68c78c7e587f9a5c85de59a90/api/submit/querybyjudger", headers=headers, data=json.dumps(data))
        ret = json.loads(response.text)
        if ret["code"]:
            # check result code
            # code should be 0
            # otherwise there are some trouble and we should raise it up!
            # TODO: raise non 0 error!
            return None
        return ret

    def problem_query(self, pid):
        headers = {

        }

        data = {
            "id": pid
        }

        ret = requests.post("https://mockapi.eolinker.com/mS5uWHX6f6afa5576ac65e68c78c7e587f9a5c85de59a90/api/problem/querybyjudger", headers=headers, data=json.dumps(data)).text
        if ret["code"]:
            pass
        return ret

    def emit_judge_result(self, submission_id, judge_id, judge_result, judge_score, used_time, used_memory, judger_log):
        headers = {
            "Origin": "http://oj.oops-sdu.cn",
        }
        data = {
            "id": submission_id,
            "judgeId": judge_id,
            "judgeResult": judge_result,
            "judgeScore": judge_score,
            "usedTime": used_time,
            "usedMemory": used_memory,
            "judgeLog": judger_log
        }

        response = requests.post("https://mockapi.eolinker.com/mS5uWHX6f6afa5576ac65e68c78c7e587f9a5c85de59a90/api/submit/update", headers=headers, data=json.dumps(data))
        if response.status_code != 200:
            pass
        return json.loads(response.text)

        

if __name__ == "__main__":
    handler = RequestHandler()
    # ret = handler.query_submit(1000001)
    # print(str(ret["data"]["code"]))
    # print(handler.problem_query(1111))
    print(handler.emit_judge_result(10001, 1, "Accepted", 10, 567, 282737, "gugudong"))