import difflib
import subprocess
from judger.model.client import Judger


def checker(test_output, std_output):
    command = "diff {} {}".format(std_output, test_output)
    if subprocess.getstatusoutput(command)[0]:
        command += " --ignore-space-change --ignore-blank-lines"
        return Judger.WRONG_ANSWER if subprocess.getstatusoutput(command)[0] else Judger.PRESENTATION_ERROR
    return Judger.SUCCESS