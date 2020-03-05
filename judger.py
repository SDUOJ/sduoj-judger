import subprocess
import difflib
from compiler import Compiler
from fetcher import Fetcher

from config import sandbox_path

JUDGE_RESULT = [
    "Accepted",
    "CPU Time Limit Exceeded",
    "Real Time Limit Exceeded",
    "Memry Limit Exceeded",
    "Runtime Error",
    "System Error",
    "Output Limit Exceeded",
    "Wrong Answer",
    "Presentation Error",
]

class Judger:
    @staticmethod
    '''
    max_cpu_time, 
    max_real_time, 
    max_memory, 
    max_stack, 
    max_process_number, 
    max_output_size, 
    exe_path,
    input_path, 
    output_path, 
    log_path, 
    exe_args, 
    exe_envs,
    seccomp_rules,
    uid,
    gid
    '''
    def run(**kwargs):
        int_args = ["max_cpu_time", "max_real_time", "max_memory", "max_stack", "max_process_number", "max_output_size", "uid", "gid"]
        str_args = ["exe_path", "input_path", "output_path", "log_path", "seccomp_rules"]
        str_list_args = ["exe_args", "exe_envs"]

        command = sandbox_path

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
                command += " --{} {}".format(arg, str(item)) for item in value
        
        return subprocess.getstatusoutput(command)

        


    def __compare(self, tid):
        path1 = "data/{}/output/output{}.txt".format(self._compile_config["pid"], tid)
        path2 = "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid)
        command = "diff {} {}".format(path1, path2)

        return subprocess.getstatusoutput(command)[0]

    # Return the result of one test
    def __one_judge(self, tid):
        # Use sandbox to run
        judge_status, self.judge_result = Judger.run()
        self.judge_result = json.loads(self.judge_result)
        if self.__compare(tid): # wrong
        # self.judge_result["result"] = "System Error" if judge_result or self.judge_result["error"] else JUDGE_RESULT[int(self.judge_result["result"])]
        self.__compare(tid)


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
            # Handle the types of error
            if self.__compare(i):
                print("WA on test", i)
            else:
                print("AC on test", i)
        
        print("AC")
        


if __name__ == "__main__":
    Judger().judge()
