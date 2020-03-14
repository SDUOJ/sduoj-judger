import json
import shutil
from config import *
from exception import *


class InitJudgeEnv(object):
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
        except Exception as e:
            # cannot remove judge dir, raise Exception here
            raise SystemInternalError("cannot remove judge workspace")
            return True
        else:
            if exception_value: # caught other error exception, raise here
                raise exception_value
                return True
            return False
