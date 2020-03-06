import os
import json
import difflib
import subprocess
from compiler import Compiler
from fetcher import Fetcher
from config import sandbox_path, JUDGE_RESULT

class Judger:

    @staticmethod    
    def __run(**kwargs):
        int_args = ["max_cpu_time", "max_real_time", "max_memory", "max_stack", "max_process_number", "max_output_size", "uid", "gid"]
        str_args = ["exe_path", "input_path", "output", "log_path", "seccomp_rules"]
        str_list_args = ["exe_args", "exe_envs"]

        command = "sudo " + sandbox_path

        for arg in int_args:
            value = kwargs.get(arg, None)
            if isinstance(value, int):
                command += " --{}={}".format(arg, value)

        for arg in str_args:
            value = kwargs.get(arg, None)
            if isinstance(value, str):
                command += " --{}={}".format(arg, str(value))

        for arg in str_list_args:
            value = kwargs.get(arg, None)
            if isinstance(value, str):
                command += " --{}={}".format(arg, str(value))
        print(command)
        return subprocess.getstatusoutput(command)     

    def __compare(self, tid, error = "WA"):
        path1 = "data/{}/output/output{}.txt".format(self._compile_config["pid"], tid)
        path2 = "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid)
        command = "diff {} {}".format(path1, path2)

        if error == "PE":
            command += " --ignore-space-change --ignore-blank-lines"

        return subprocess.getstatusoutput(command)[0]

    def __handle_error(self, tid):
        # Handle the types of error
        js = json.loads(self.judge_result)
        info = JUDGE_RESULT[js["result"]] + " on test {}".format(tid)
        print(info)
        return

    # Return the result of one test
    def __one_judge(self, tid):
        # Use sandbox to run
        judge_status, self.judge_result = Judger.__run(
            exe_path = "test/{}/main".format(self._compile_config["pid"]),
            input_path = "data/{}/input/input{}.txt".format(self._compile_config["pid"], tid),
            output = "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid),
            seccomp_rules = "c_cpp"
        )
        js = json.loads(self.judge_result)
        if judge_status != 0:
            js["result"] = 5
        elif js["result"] == 0:
            if self.__compare(tid):
                js["result"] = 7
                if self.__compare(tid, "PE") == 0:
                    js["result"] = 8
            
        self.judge_result = json.dumps(js)


    def __spj(self, tid):
        # A 测
        # spj 测
        # compare spj.out output.txt

        # Use sandbox to run the user code
        judge_status, self.judge_result = Judger.__run(
            exe_path = "test/{}/main".format(self._compile_config["pid"]),
            input_path = "data/{}/input/input{}.txt".format(self._compile_config["pid"], tid),
            output = "test/{}/spj/output{}.txt".format(self._compile_config["pid"], tid),
            seccomp_rules = "c_cpp"
        )
        js = json.loads(self.judge_result)
        
        # 
        if judge_status != 0:
            js["result"] = 5
        else:
            spj_status, spj_result = Judger.__run(
                exe_path = "test/{}/spj/main".format(self._compile_config["pid"]),
                output = "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid),
                exe_args = "data/{}/input/input{}.txt".format(self._compile_config["pid"], tid) \
                            + " test/{}/output/output{}.txt".format(self._compile_config["pid"], tid),
                seccomp_rules = "c_cpp"
            )
            if spj_status != 0:
                js["result"] = 5
            elif self.__compare(tid, "PE") == 0:
                js["result"] = 0
            else:
                js["result"] = 7        
        
        self.judge_result = json.dumps(js)

    def judge(self):
        # Fetch the code file
        fetcher = Fetcher()
        self._compile_config = fetcher.GenerateFile()

        self._src_path = self._compile_config["src_path"]

        # Compile the code
        self._compiler = Compiler(self._src_path)
        ret = self._compiler.compile()
        if ret[0] != 0:
            return "CE"

        # Acquire the number of the input data
        num = len(os.listdir("data/{}/input".format(self._compile_config["pid"])))

        # Acquire the flag of spj
        spj_flag = (len(os.listdir("data/{}".format(self._compile_config["pid"]))) == 3)

        # Test the input data one by one
        for i in range(1, num+1):
            if(spj_flag):
                self.__spj(i)
            else:
                self.__one_judge(i)
            self.__handle_error(i)
        


if __name__ == "__main__":
    Judger().judge()
