class JudgeCustomError(Exception):
    def __init__(self, err_msg=""):
        super().__init__(self)
        self.err_msg = err_msg
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