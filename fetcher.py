import json


class Fetcher:

    @staticmethod
    def FetchStr():
        # API -> SQL
        str = open("file/E.cc", "r+").read()
        js = {"Language": "cc", 
              "Code": str, 
              "pid": 1001, 
              "max_memory": "16777216", 
              "max_cpu_time": "1000",
              "max_real_time": "1000",
            }
        return json.dumps(js)

    # Return the code file
    @classmethod
    def GenerateFile(self):
        # Acquire arguments
        js = json.loads(Fetcher.FetchStr())
        language = js["Language"]
        code = js["Code"]
        pid = js["pid"]

        path = "test/{}/main.{}".format(pid, language)

        # Write file
        fo = open(path, "w")
        fo.write(code)

        # Close File
        fo.close()

        # delete Code
        del js["Code"]
        # add source file path
        js["src_path"] = path
        return js
