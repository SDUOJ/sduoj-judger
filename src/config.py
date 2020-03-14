import os
import pwd
import grp


SANDBOX_PATH = "../../sduoj-sandbox/sandbox"

BASE_WORKSPACE_PATH = "workspace/"
BASE_LOG_PATH = "log/"
BASE_DATA_PATH = "data/"

SANDBOX_LOG_PATH = os.path.join(BASE_LOG_PATH, "sandbox.log")


NOBODY_UID = pwd.getpwnam("nobody").pw_uid
NOBODY_GID = grp.getgrnam("nogroup").gr_gid
