class JudgeCustomError(Exception):
    def __init__(self, err_msg="", case_id=-1):
        super().__init__(self)
        self.err_msg = err_msg
        self.case_id = case_id
    def where(self):
        return self.case_id;
    def __str__(self):
        return self.err_msg

class UserCompileError(JudgeCustomError):
    pass

class SpjCompileError(JudgeCustomError):
    pass

class SpjError(JudgeCustomError):
    pass

class SystemInternalError(JudgeCustomError):
    pass

class SandboxInternalError(JudgeCustomError):
    pass