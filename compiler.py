import subprocess


class Compiler:
    # Return the executable file
    def Compile(self, path):
        exec_path = "test/test"
        command = "g++ " + path + " -o " + exec_path
        subprocess.getstatusoutput(command)
        return exec_path
