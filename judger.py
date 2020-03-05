import subprocess
import json
import compiler
import fetcher


class Judger:

    def OneJudge(self):
        return

    def SpecialJudge(self):
        return

    def Judge(self):
        # Generate the executable file path
        # path = GenerateFile(SendFile())
        # path = Compile(path)
        # path = "../sduoj-judger/"+path

        # Use sandbox to run
        command = "../"

        # ./sandbox --exe_path=path --
        #
        # {time: space: }
