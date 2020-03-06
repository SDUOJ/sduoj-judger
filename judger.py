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
            if isinstance(value, list):
                command += " --{}={}".format(arg, str(value))

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
        if js["result"] == 0:
            print("AC on test", tid)
        else:
            print("WA on test", tid)
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
        if js["result"] == 0:
            print("txt")
            if self.__compare(tid):
                js["result"] = 7
            elif self.__compare(tid, "PE"):
                js["result"] = 8
        self.judge_result = json.dumps(js)


    def __spj(self):
        return

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

        for i in range(1, 3):
            self.__one_judge(i)
            self.__handle_error(i)
        


if __name__ == "__main__":
    Judger().judge()
