import os
import pwd
import grp
import yaml


SANDBOX_PATH = "/usr/bin/sandbox"

BASE_WORKSPACE_PATH = "workspace/"
BASE_LOG_PATH = "log/"
BASE_DATA_PATH = "test/data/"

CONFIG_FILE_PATH = "config.yaml"
SANDBOX_LOG_PATH = os.path.join(BASE_LOG_PATH, "sandbox.log")
JUDGER_LOG_PATH = os.path.join(BASE_LOG_PATH, "judger.log")

NOBODY_UID = pwd.getpwnam("nobody").pw_uid
NOBODY_GID = grp.getgrnam("nogroup").gr_gid

def _load_config():
    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            return yaml.load(f)
    except FileNotFoundError:
        # TODO: no config file
        exit(1)

CONFIG = _load_config()

if __name__ == "__main__":
    print(CONFIG)