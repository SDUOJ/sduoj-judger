class JudgeCustomError(Exception):
    def __init__(self, err_msg="", case_id=-1, *args):
        super().__init__(err_msg, case_id, *args)
        self.err_msg = err_msg
        self.case_id = case_id
    def where(self):
        return self.case_id;
    def __str__(self):
        return self.__class__.__name__ + ": " + self.err_msg

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


class HTTPError(Exception):
    def __init__(self, message, *args):
        super().__init__(message, *args)
        self.message = message