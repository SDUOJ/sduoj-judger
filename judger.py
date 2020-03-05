import subprocess
import difflib
from compiler import Compiler
from fetcher import Fetcher

from config import sandbox_path


class Judger:

    def __compare(self,tid):
        path1 = "data/{}/output/output{}.txt".format(self._compile_config["pid"], tid)
        path2 = "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid)
        std_output = open(path1, 'U').readlines()
        user_output = open(path2, 'U').readlines()
        if set(std_output)-set(user_output) == set():
            return True
        else:
            return False

    # Return the result of one test
    def __one_judge(self, tid):
        # Use sandbox to run
        command = "sudo {} \
                    --exe_path {} \
                    --input_path {}\
                    --output_path {}\
                    --seccomp_rules {} \
                    --max_memory {} \
                    --max_cpu_time {}".format(sandbox_path,
                            self._compiler.exec_path,
                            "data/{}/input/input{}.txt".format(self._compile_config["pid"], tid),
                            "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid),
                            "c_cpp",
                            self._compile_config["max_memory"],
                            self._compile_config["max_cpu_time"],
                        )
        subprocess.getstatusoutput(command)

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
            if __compare(tid) == False:
                return "Wrong Answer"
        
        return "Accepted"
        


if __name__ == "__main__":
    Judger().judge()
