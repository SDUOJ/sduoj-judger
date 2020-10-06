import os
import json
import subprocess
import shutil

from judger.lang import LANG_CONFIG
from judger.config import *
from judger.exception import *

import logging
import coloredlogs

logger = logging.getLogger(__name__)
coloredlogs.install(level="DEBUG")

DEBUG_MODE = True

def run(**kwargs):
    int_args = ["max_cpu_time", "max_real_time", "max_memory",
                "max_stack", "max_process_number", "max_output_size", "uid", "gid"]
    str_args = ["exe_path", "input_path",
                "output_path", "log_path", "seccomp_rules"]
    str_list_args = ["exe_args", "exe_envs"]

    command = SANDBOX_PATH
    
    for arg in int_args:
        value = kwargs.get(arg, None)
        
        if value is None:
            continue
        if not isinstance(value, int):
            raise ValueError("'{}' must be an int".format(arg))
        command += " --{}={}".format(arg, value)

    for arg in str_args:
        value = kwargs.get(arg, None)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError("'{}' must be a string".format(arg))
        command += " --{}=\"{}\"".format(arg, str(value))

    for arg in str_list_args:
        value = kwargs.get(arg, None)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError("'{}' must be a list".format(arg))
        for item in value:
            command += " --{}=\"{}\"".format(arg, str(item))

    print(command)
    err, out = subprocess.getstatusoutput(command)
    if err:    # system cannot launch sandbox sucessfully
        raise SystemInternalError(out, kwargs.get("case_id", -1))
    result = json.loads(out)
    return result



class WorkspaceInitializer(object):
    def __init__(self, workspace_dir, pid, submission_id):
        self._workspace_dir = os.path.join(
            workspace_dir, "{}-{}".format(pid, submission_id))

    def __enter__(self):
        try:
            self._test_output_dir = os.path.join(self._workspace_dir, "output")
            if not os.path.exists(self._workspace_dir):
                os.mkdir(self._workspace_dir)
            if not os.path.exists(self._test_output_dir):
                os.mkdir(self._test_output_dir)
            os.chown(self._workspace_dir, NOBODY_UID, 0)
            os.chmod(self._workspace_dir, 0o711)
        except Exception as e:
            # cannot create judge dir, raise Exception here
            err = SystemInternalError("Cannot create judge workspace \"{}\"".format(self._workspace_dir))
            logger.error(str(err))
            raise err
            pass
        return self._workspace_dir, self._test_output_dir

    def __exit__(self, exception_type, exception_value, exception_traceback):
        try:
            if not DEBUG_MODE:
                shutil.rmtree(self._workspace_dir)
            pass
        except Exception as e:
            # cannot remove judge dir, raise Exception here
            logger.warn("Cannot remove judge workspace \"{}\"".format(self._workspace_dir))
            # raise SystemInternalError("cannot remove judge workspace")
            return True
        else:
            if exception_value:  # caught other error exception, raise here
                raise exception_value
                return True
            return False


class Judger(object):
    SUCCESS = 0
    CPU_TIME_LIMIT_EXCEEDED = 1
    REAL_TIME_LIMIT_EXCEEDED = 2
    MEMORY_LIMIT_EXCEEDED = 3
    RUNTIME_ERROR = 4
    SYSTEM_ERROR = 5
    WRONG_ANSWER = 6
    PRESENTATION_ERROR = 7

    COMPILE_ERROR = 8

    SPJ_ERROR = 255
    SPJ_WA = 1
    SPJ_SUCCESS = 0

    RETURN_TYPE = {
        SUCCESS: 1,
        CPU_TIME_LIMIT_EXCEEDED: 2,
        REAL_TIME_LIMIT_EXCEEDED: 2,
        MEMORY_LIMIT_EXCEEDED: 3,
        RUNTIME_ERROR: 4,
        SYSTEM_ERROR: 5,
        WRONG_ANSWER: 6,
        PRESENTATION_ERROR: 7,
        COMPILE_ERROR: 8,
    }
    def __init__(self, 
                submission_id, 
                pid, 
                code, 
                lang, 
                run_config, 
                data_path,
                # input_path, 
                input_cases: list, 
                # answer_path, 
                output_answers: list, 
                checker=None, 
                spj=None, 
                oimode=False, 
                **kwargs):

        self._submission_id = submission_id
        self._pid = pid
        self._code = code
        self._lang = lang
        self._run_config = run_config          # resource limit
        # self._input_path = os.path.join(BASE_DATA_PATH, data_path, "input")
        self._basic_path = data_path
        # input test data, should be a list containing the path of all test datas
        self._input = input_cases
        # self._answer_path = os.path.join(BASE_DATA_PATH, data_path, "output")
        # standard output answer, should be a list containing the path of all answers
        self._output = output_answers
        self._checker = checker     # TODO: checker can be customed
        self._spj = spj
        self._oimode = oimode
        self._kwargs = kwargs

        self._case_id = -1

    def judge(self):
        self._lang_config = LANG_CONFIG[self._lang]

        with WorkspaceInitializer(BASE_WORKSPACE_PATH, self._pid, self._submission_id) as paths:
            workspace_dir, test_output_path = paths
            src_path = os.path.join(workspace_dir, self._lang_config["src_name"])

            # compile the code here
            with open(src_path, "w", encoding="utf8") as f:
                f.write(self._code)

            os.chown(src_path, NOBODY_UID, 0)
            os.chmod(src_path, 0o400)
            logger.info("Compiling \"{}\"".format(src_path))
            self._exe_path, self._compile_info = self.compile(compile_config=self._lang_config,
                                                            src_path=src_path,
                                                            output_dir=workspace_dir)
            # TODO: compile down!
            logger.info("Compile down \"{}\"".format(self._exe_path))
            os.chown(self._exe_path, NOBODY_UID, 0)
            os.chmod(self._exe_path, 0o500)

            if self._spj:
                self._spj_exe_path = self._spj.get("exe_path", None)
                self._spj_config = LANG_CONFIG[self._spj["lang"]]
                # if spj_exe_path is not realiable, recompile it!
                if not self._spj_exe_path or not os.path.isfile(self._spj_exe_path):
                    # compile the spj code
                    logger.info("SPJ Compiling \"{}\"".format(self._spj["src_path"]))
                    self._spj_exe_path, self._spj_compiler_info = self.compile(compile_config=self._spj_config, 
                                                                src_path=self._spj["src_path"],
                                                                output_dir=workspace_dir,
                                                                spj_name="spj")
                    # TODO: spj compile down!
                    logger.info("SPJ Compile down \"{}\"".format(self._spj_exe_path))

            judge_result = {
                "submission_id": self._submission_id,
                "pid": self._pid,
                "result": []
            }
            self._case_id = 0
            logger.info("{}-{} Judging {} checkpoints...".format(self._pid, self._submission_id, len(self._input)))
            for input_case, output_case in zip(self._input, self._output):
                input_path = os.path.join(self._basic_path, input_case)
                answer_path = os.path.join(self._basic_path, output_case)
                output_path = os.path.join(test_output_path, output_case)

                case_result = self.one_judge(run_config=self._run_config,
                                               lang_config=self._lang_config,
                                               exe_path=self._exe_path,
                                               test_input=input_path,
                                               test_output=output_path,
                                               std_output=answer_path)
                judge_result["result"].append(case_result)
    
                handler = self._kwargs.get("handler", None)
                if handler:
                    handler.send_checkpoint_result([
                        str(self._submission_id),
                        self._case_id,
                        Judger.RETURN_TYPE[case_result["result"]],
                        int(case_result["cpu_time"]),
                        int(case_result["memory"]) // 1024,
                    ])
                
                if case_result["result"] and not self._oimode:
                    break
                self._case_id += 1

            return judge_result

    # Return the result of one test
    def one_judge(self, run_config, lang_config, exe_path, test_input, test_output, std_output):
        # Use sandbox to run
        judge_result = run(exe_path=exe_path,
                            exe_args=lang_config["run_args"],
                            exe_envs=lang_config["run_envs"],
                            seccomp_rules=lang_config["seccomp_rules"],

                            input_path=test_input,
                            output_path=test_output,
                            log_path=SANDBOX_LOG_PATH,

                            max_cpu_time=run_config.get("max_cpu_time", None),
                            max_real_time=run_config.get("max_real_time", None),
                            max_memory=run_config.get("max_memory", None) * 1024,
                            max_stack=run_config.get("max_stack", None),

                            uid=NOBODY_UID,
                            gid=NOBODY_GID,
                        )

        if judge_result["result"] == Judger.SUCCESS:
            judge_result["result"] = self.__spj_check(self._spj_config, test_input, test_output) if self._spj \
                else self._checker(test_output=test_output, std_output=std_output)
        elif judge_result["result"] == Judger.SYSTEM_ERROR:
            logger.error("Sandbox Internal Error #{}, signal {}".format(judge_result["error"], judge_result["signal"]))
            raise SandboxInternalError("Sandbox Internal Error #{}, signal {}".format(judge_result["error"], judge_result["signal"]))
        return judge_result

    def spj_check(self, spj_config, test_input, test_output):
        # Use sandbox to run the user code
        spj_result = Judger.__run(
            exe_path=self._spj_exe_path,
            exe_args=[test_input, test_output],
            seccomp_rules=spj_config["seccomp_rules"],
            log_path=SANDBOX_LOG_PATH,
        )

        # exit code should be 0 or 1
        if spj_result["exit_code"] != Judger.SPJ_SUCCESS and spj_result["exit_code"] != Judger.SPJ_WA:
            raise SpjError("Unexcepted spj exit code %s" % str(spj_result["exit_code"]), self._case_id)

        if spj_result["exit_code"] == Judger.SPJ_SUCCESS:
            return Judger.SUCCESS
        else:
            return Judger.WRONG_ANSWER

    def compile(self, compile_config, src_path, output_dir):
        exe_path = os.path.join(output_dir, compile_config["exe_name"])
        command = compile_config["compile_command"].format(src_path=src_path, exe_path=exe_path)
        print(command)
        _command = command.split(" ")
        compiler_out = os.path.join(output_dir, "compiler.out")
        try:
            compile_result = run(
                max_cpu_time=compile_config["compile_cpu_time"],
                max_real_time=compile_config["compile_real_time"],
                max_memory=compile_config["compile_memory"],
                max_stack=128 * 1024 * 1024,
                max_output_size=1024 * 1024,
                exe_path=_command[0],
                exe_args=_command[1::],
                exe_envs=["PATH="+os.getenv("PATH")],
                input_path="/dev/null",
                output_path=compiler_out,
            )
        except SystemInternalError as e:
            raise UserCompileError(e.err_msg)
        else:
            if not os.path.exists(compiler_out):
                raise UserCompileError("cannot get compiler output")
            with open(compiler_out, "r") as f:
                compiler_info = f.read()
            if compile_result["result"]:
                raise UserCompileError(compiler_info)
            return exe_path, compiler_info

    def compile_spj(self, compile_config, src_path, output_dir, spj_name):
        exe_path = os.path.join(output_dir, spj_name)
        command = compile_config["compile_command"].format(src_path=src_path, exe_path=exe_path)
        _command = command.split(" ")
        compiler_out = os.path.join(output_dir, "compiler_spj.out")
        try:
            compile_result = run(
                max_cpu_time=compile_config["compile_cpu_time"],
                max_real_time=compile_config["compile_real_time"],
                max_memory=compile_config["compile_memory"],
                max_stack=128 * 1024 * 1024,
                max_output_size=1024 * 1024,
                exe_path=_command[0],
                exe_args=_command[1::],
                exe_envs=["PATH="+os.getenv("PATH")],
                input_path="/dev/null",
                output_path=compiler_out,
            )
        except SandboxInternalError as e:
            raise SpjCompileError(e.err_msg)
        else:
            if not os.path.exists(compiler_out):
                raise SpjCompileError("cannot get compiler output")
            with open(compiler_out, "r") as f:
                compiler_info = f.read()
                if compile_result["result"]:
                    raise SpjCompileError(compiler_info)
            return exe_path, compiler_info
