import requests
import json


class RequestHandler(object):
    
    def query_submit(self, submission_id):
        headers = {
            "Content-Type": "application/json",
            "Origin": "http://oj.oops-sdu.cn",
        }

        data = {
            "id": submission_id
        }

        response = requests.post("https://mockapi.eolinker.com/mS5uWHX6f6afa5576ac65e68c78c7e587f9a5c85de59a90/api/submit/querybyjudger", headers=headers, data=json.dumps(data))
        ret = json.loads(response.text)
        return ret

if __name__ == "__main__":
    handler = RequestHandler()
    print(handler.query_submit(1000001))