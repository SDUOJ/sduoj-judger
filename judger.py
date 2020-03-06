import subprocess
import difflib
from compiler import Compiler
from fetcher import Fetcher
from config import sandbox_path, JUDGE_RESULT

class Judger:

    @staticmethod    
    def __run(**kwargs):
        int_args = ["max_cpu_time", "max_real_time", "max_memory", "max_stack", "max_process_number", "max_output_size", "uid", "gid"]
        str_args = ["exe_path", "input_path", "output_path", "log_path", "seccomp_rules"]
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

    def __handle_error(self, error):
        return

    # Return the result of one test
    def __one_judge(self, tid):
        # Use sandbox to run
        judge_status, self.judge_result = Judger.__run(
            exe_path = "test/{}/main.cc".format(self._compile_config["pid"]),
            input_path = "data/{}/input/input{}.txt".format(self._compile_config["pid"], tid),
            output_path = "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid),
            seccomp_rules = "c_cpp"
        )
        if judge_status != 0:
            self.judge_result["result"] = "System Error"
        if self.judge_result["result"] == 0:
            if self.__compare(tid):
                self.judge_result["result"] = "Wrong Answer"    
            if self.__compare(tid, "PE"):
                self.judge_result["result"] = "Presentation Error"
        return self.judge_result


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
            print(type(self.__one_judge(i)))
            # Handle the types of error
            if self.__compare(i):
                print("WA on test", i)
            else:
                print("AC on test", i)
        
        print("AC")
        


if __name__ == "__main__":
    Judger().judge()
