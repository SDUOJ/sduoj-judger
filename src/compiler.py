import subprocess
import os
from lang import LANG_CONFIG


class Compiler:
    # Return the compile infomation
    def compile(self, compile_config, src_path, output_dir):
        exe_path = os.path.join(output_dir, compile_config["exe_name"])
        command = compile_config["compile_command"].format(
            src_path=src_path, exe_path=exe_path)
        compile_status, compile_info = subprocess.getstatusoutput(command)
        if compile_status:
            # TODO: raise CompileError here
            pass
        return compile_info, exe_path

    def compile_spj(self, compile_config, src_path, output_dir, spj_name):
        exe_path = os.path.join(output_dir, spj_name)
        command = compile_config["compile_command"].format(
            src_path=src_path, exe_path=exe_path)
        compile_status, compile_info = subprocess.getstatusoutput(command)
        if compile_status:
            # TODO: raise CompileError here
            pass
        return compile_info, exe_path