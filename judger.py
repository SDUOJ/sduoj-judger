import os
import json
import difflib
import subprocess
from initialize import InitJudgeEnv
from compiler import Compiler
from config import *
from lang import *


def __checker(test_output, std_output):
    command = "diff {} {}".format(std_output, test_output)
    if subprocess.getstatusoutput(command)[0]:
        command += " --ignore-space-change --ignore-blank-lines"
        return Judger.WRONG_ANSWER if subprocess.getstatusoutput(command)[0] else Judger.SUCCESS
    return Judger.SUCCESS


class Judger(object):
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

    def __init__(self, submission_id, pid, code, lang, run_config, test_path, input_cases: list, output_answers: list, checker=None, spj=None, oimode=False, **kwargs):
        self._submission_id = submission_id
        self._pid = pid
        self._code = code
        self._lang = lang
        self._run_config = run_config          # resource limit
        self._test_path = test_path
        # input test data, should be a list containing the path of all test datas
        self._input = input_cases
        # standard output answer, should be a list containing the path of all answers
        self._output = output_answers
        self._checker = checker
        self._spj = spj
        self._oimode = oimode

    def judge(self):
        self._lang_config = LANG_CONFIG[self._lang]

        with InitJudgeEnv(BASE_WORKSPACE_PATH, self._pid, self._submission_id) as paths:
            workspace_dir, test_output_path = paths
            src_path = os.path.join(
                workspace_dir, self._lang_config["src_name"])

            # compile the code here
            with open(src_path, "w", encoding="utf8") as f:
                f.write(self._code)
            os.chown(src_path, NOBODY_UID, NOBODY_GID)
            os.chmod(src_path, 0o400)

            compile_info, self._exe_path = Compiler().compile(compile_config=self._lang_config,
                                                              src_path=src_path,
                                                              output_dir=workspace_dir)
            os.chown(self._exe_path, NOBODY_UID, 0)
            os.chmod(self._exe_path, 0o500)
            # print(compile_info)

            if self._spj:
                # compile the spj code
                self._spj_config = LANG_CONFIG[self._spj["lang"]]
                compile_info, self._spj_exe_path = Compiler().compile_spj(compile_config=self._spj_config,
                                                                          src_path=self._spj["src_path"],
                                                                          output_dir=workspace_dir,
                                                                          spj_name="spj")
                os.chown(self._spj_exe_path, NOBODY_UID, 0)
                os.chmod(self._spj_exe_path, 0o500)
                # print(compile_info)

            judge_result = {
                "submission_id": self._submission_id,
                "pid": self._pid,
                "result": {}
            }
            for input_case, output_case in zip(self._input, self._output):
                input_path = os.path.join(self._test_path, "input", input_case)
                answer_path = os.path.join(
                    self._test_path, "output", output_case)
                output_path = os.path.join(test_output_path, input_case)

                case_result = self.__one_judge(run_config=self._run_config,
                                               lang_config=self._lang_config,
                                               exe_path=self._exe_path,
                                               test_input=input_path,
                                               test_output=output_path,
                                               std_output=answer_path)

                judge_result["result"][input_case] = case_result
                if case_result["result"] and not self._oimode:
                    break

            print(judge_result)

    # Return the result of one test
    def __one_judge(self, run_config, lang_config, exe_path, test_input, test_output, std_output):
        # Use sandbox to run
        judge_status, judge_result = Judger.__run(
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

        if judge_status or judge_result["error"]:
            judge_result["result"] = Judger.SYSTEM_ERROR

        if judge_result["result"] == Judger.SUCCESS:
            judge_result["result"] = self.__spj_check(self._spj_config, test_input, test_output) if self._spj else self._checker(
                test_output=test_output, std_output=std_output)

        return judge_result

    def __spj_check(self, spj_config, test_input, test_output):
        # Use sandbox to run the user code
        spj_status, spj_result = Judger.__run(
            exe_path=self._spj_exe_path,
            exe_args=[test_input, test_output],
            seccomp_rules=spj_config["seccomp_rules"],
        )

        if spj_status or spj_result["error"] or \
            (spj_result["exit_code"] != Judger.SPJ_SUCCESS and spj_result["exit_code"] != Judger.SPJ_WA) or \
                spj_result["result"] == Judger.SYSTEM_ERROR:
            return Judger.SYSTEM_ERROR

        if spj_result["exit_code"] == Judger.SPJ_SUCCESS:
            return Judger.SUCCESS

        if spj_result["exit_code"] == Judger.SPJ_WA:
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

        judge_status, judge_result = subprocess.getstatusoutput(command)
        return judge_status, json.loads(judge_result)


if __name__ == "__main__":
    from fetcher import Fetcher
    js = json.loads(Fetcher.FetchStr())

    print(js)

    client = Judger(submission_id=js["submission_id"],
                    pid=js["pid"],
                    code=js["code"],
                    lang=js["lang"],
                    run_config=js["run_config"],
                    test_path="data/1001",
                    input_cases=["input1.txt", "input2.txt"],
                    output_answers=["output1.txt", "output2.txt"],
                    # checker=checker,
                    spj=js["spj"],
                    )
    client.judge()
