import subprocess
from compiler import Compiler
from fetcher import Fetcher

from config import sandbox_path


class Judger:

    def __one_judge(self, tid):
        # Use sandbox to run
        command = "sudo {} \
                    --exe_path {} \
                    --input_path {}\
                    --output_path {}\
                    --seccomp_rules {} \
                    --max_memory {} \
                    --max_cpu_time {} ".format(sandbox_path, 
                                                self._compiler.exec_path, 
                                                "test/{}/input/input{}.txt".format(self._compile_config["pid"], tid), 
                                                "test/{}/output/output{}.txt".format(self._compile_config["pid"], tid),
                                                "c_cpp", 
                                                self._compile_config["max_memory"], 
                                                self._compile_config["max_cpu_time"], 
                                                #self._compile_config["max_real_time"]
                                            )
        return subprocess.getstatusoutput(command)

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
            pass # CE
            return

        for i in range(1, 3):
            print(self.__one_judge(i))
        


if __name__ == "__main__":
    Judger().judge()
