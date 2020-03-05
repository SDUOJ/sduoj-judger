import subprocess
from config import  compile_config

class Compiler:

    def __init__(self, path):
        self._path = path
        self.exec_path, self._lang = path.split('.')

    # Return the compile infomation
    def compile(self):
        command = compile_config[self._lang]
        if self._lang == "py":
            return subprocess.getstatusoutput(command.format(self._path))
        return subprocess.getstatusoutput(command.format(self._path, self.exec_path))

