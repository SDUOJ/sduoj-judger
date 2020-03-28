import os
import json
import subprocess
import shutil

from judger.model.compiler import Compiler
from judger.lang import LANG_CONFIG
from judger.config import *
from judger.exception import *


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
        except Exception as e:
            # cannot create judge dir, raise Exception here
            raise SystemInternalError("cannot create judge workspace")
            pass
        return self._workspace_dir, self._test_output_dir

    def __exit__(self, exception_type, exception_value, exception_traceback):
        try:
            shutil.rmtree(self._workspace_dir)
            pass
        except Exception as e:
            # cannot remove judge dir, raise Exception here
            raise SystemInternalError("cannot remove judge workspace")
            return True
        else:
            if exception_value:  # caught other error exception, raise here
                raise exception_value
                return True
            return False


class Judger(object):
    RETURN_TYPE = ["AC", "TLE", "TLE", "MLE", "RE", "SE", "WA", "PE"]

    SUCCESS = 0
    CPU_TIME_LIMIT_EXCEEDED = 1
    REAL_TIME_LIMIT_EXCEEDED = 2
    MEMORY_LIMIT_EXCEEDED = 3
    RUNTIME_ERROR = 4
    SYSTEM_ERROR = 5
    WRONG_ANSWER = 6
    PRESENTATION_ERROR = 7

    SPJ_ERROR = 255
    SPJ_WA = 1
    SPJ_SUCCESS = 0

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
        self._input_path = os.path.join(BASE_DATA_PATH, data_path, "input")
        # input test data, should be a list containing the path of all test datas
        self._input = input_cases
        self._answer_path = os.path.join(BASE_DATA_PATH, data_path, "output")
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
            src_path = os.path.join(
                workspace_dir, self._lang_config["src_name"])

            # compile the code here
            with open(src_path, "w", encoding="utf8") as f:
                f.write(self._code)

            compile_info, self._exe_path = Compiler().compile(compile_config=self._lang_config,
                                                              src_path=src_path,
                                                              output_dir=workspace_dir)

            if self._spj:
                self._spj_exe_path = self._spj.get("exe_path", None)
                self._spj_config = LANG_CONFIG[self._spj["lang"]]
                # if spj_exe_path is not realiable, recompile it!
                if not self._spj_exe_path or not os.path.isfile(self._spj_exe_path):
                    # compile the spj code
                    compile_info, self._spj_exe_path = Compiler().compile_spj(compile_config=self._spj_config,
                                                                              src_path=self._spj["src_path"],
                                                                              output_dir=workspace_dir,
                                                                              spj_name="spj")

            judge_result = {
                "submission_id": self._submission_id,
                "pid": self._pid,
                "result": {}
            }
            self._case_id = 0
            for input_case, output_case in zip(self._input, self._output):
                input_path = os.path.join(self._input_path, input_case)
                answer_path = os.path.join(self._answer_path, output_case)
                output_path = os.path.join(test_output_path, output_case)

                case_result = self.__one_judge(run_config=self._run_config,
                                               lang_config=self._lang_config,
                                               exe_path=self._exe_path,
                                               test_input=input_path,
                                               test_output=output_path,
                                               std_output=answer_path)
                handler = self._kwargs.get("handler", None)
                if handler:
                    handler.send_judge_result(submission_id=self._submission_id, 
                                              judger_id=CONFIG["uname"], 
                                              judge_result=Judger.RETURN_TYPE[case_result["result"]], 
                                              judge_score=0, 
                                              used_time=case_result["cpu_time"],
                                              used_memory=case_result["memory"],
                                              judger_log="")
                judge_result["result"][input_case] = case_result
                if case_result["result"] and not self._oimode:
                    break
                self._case_id += 1

            return judge_result

    # Return the result of one test
    def __one_judge(self, run_config, lang_config, exe_path, test_input, test_output, std_output):
        # Use sandbox to run
        judge_result = Judger.__run(
            exe_path=exe_path,
            exe_args=lang_config["run_args"],
            exe_envs=lang_config["run_envs"],
            seccomp_rules=lang_config["seccomp_rules"],

            input_path=test_input,
            output_path=test_output,
            log_path=SANDBOX_LOG_PATH,

            max_cpu_time=run_config.get("max_cpu_time", None),
            max_real_time=run_config.get("max_real_time", None),
            max_memory=lang_config.get("max_memory", None),
            max_stack=run_config.get("max_stack", None),

            uid=NOBODY_UID,
            gid=NOBODY_GID,
        )

        if judge_result["result"] == Judger.SUCCESS:
            judge_result["result"] = self.__spj_check(self._spj_config, test_input, test_output) if self._spj \
                else self._checker(test_output=test_output, std_output=std_output)

        return judge_result

    def __spj_check(self, spj_config, test_input, test_output):
        # Use sandbox to run the user code
        spj_result = Judger.__run(
            exe_path=self._spj_exe_path,
            exe_args=[test_input, test_output],
            seccomp_rules=spj_config["seccomp_rules"],
            log_path=SANDBOX_LOG_PATH,
        )

        # exit code should be 0 or 1
        if spj_result["exit_code"] != Judger.SPJ_SUCCESS and spj_result["exit_code"] != Judger.SPJ_WA:
            raise SpjError("Unexcepted spj exit code %s" %
                           str(spj_result["exit_code"]), self._case_id)

        if spj_result["exit_code"] == Judger.SPJ_SUCCESS:
            return Judger.SUCCESS
        else:
            return Judger.WRONG_ANSWER

    @staticmethod
    def __run(**kwargs):
        int_args = ["max_cpu_time", "max_real_time", "max_memory",
                    "max_stack", "max_process_number", "max_output_size", "uid", "gid"]
        str_args = ["exe_path", "input_path",
                    "output_path", "log_path", "seccomp_rules"]
        str_list_args = ["exe_args", "exe_envs"]

        command = SANDBOX_PATH

        for arg in int_args:
            value = kwargs.get(arg, None)
            if isinstance(value, int):
                command += " --{}={}".format(arg, value)

        for arg in str_args:
            value = kwargs.get(arg, None)
            if isinstance(value, str):
                command += " --{}={}".format(arg, str(value))

        for arg in str_list_args:
            value = kwargs.get(arg, None)
            if isinstance(value, list):
                for item in value:
                    command += " --{}={}".format(arg, str(item))
        # print(command)
        judge_status, judge_result = subprocess.getstatusoutput(command)
        if judge_status:    # system cannot launch sandbox sucessfully
            raise SystemInternalError(judge_result, kwargs.get("case_id", -1))
        
        judge_result = json.loads(judge_result)
        if judge_result["result"] == Judger.SYSTEM_ERROR:   # give error number
            raise SandboxInternalError("sandbox internal error, signal=%d, errno=%d" % (judge_result["signal"], judge_result["error"]), kwargs.get("case_id", -1))
        return judge_result
