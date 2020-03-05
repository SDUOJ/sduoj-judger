import subprocess
from compiler import Compiler
from fetcher import Fetcher


class Judger:

    def OneJudge(self):
        return

    def SpecialJudge(self):
        return

    def Judge(self):
        # Fetch the code file
        fetcher = Fetcher()
        path = fetcher.GenerateFile()

        # Compile the code
        compiler = Compiler()

        # path = GenerateFile(SendFile())
        # path = Compile(path)
        # path = "../sduoj-judger/"+path

        # Use sandbox to run
        command = "../"

        # ./sandbox --exe_path=path --
        #
        # {time: space: }


A = Judger()
A.Judge()
