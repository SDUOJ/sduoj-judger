import subprocess


class Compiler:
    # Return the executable file
    def Compile(path):
        exec_path = "Test/test"
        command = "g++ " + path + " -o " + exec_path
        subprocess.getstatusoutput(command)
        return exec_path
