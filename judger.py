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
        path = compiler.Compile(path)
        path = "../sduoj-judger/"+path

        # Use sandbox to run
        command = "../"


A = Judger()
A.Judge()
