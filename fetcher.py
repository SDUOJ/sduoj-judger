import json


class Fetcher:
    def FetchStr(self):
        str = open("File/E.cpp", "r+").read()
        js = {"Language": "cpp", "Code": str}
        return json.dumps(js)

    # Return the code file
    def GenerateFile(self):
        str = self.FetchStr()

        # Acquire arguments
        js = json.loads(str)
        language = js["Language"]
        code = js["Code"]
        path = "test/test." + language

        # Write file
        fo = open(path, "w")
        fo.write(code)

        # Close File
        fo.close()

        return path
