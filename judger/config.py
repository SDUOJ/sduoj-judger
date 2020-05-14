import os
import pwd
import grp
import yaml


SANDBOX_PATH = "/usr/bin/sandbox"

BASE_WORKSPACE_PATH = "workspace/"
BASE_LOG_PATH = "log/"
BASE_DATA_PATH = "data/"

CONFIG_FILE_PATH = "config.yaml"
SANDBOX_LOG_PATH = os.path.join(BASE_LOG_PATH, "sandbox.log")
JUDGER_LOG_PATH = os.path.join(BASE_LOG_PATH, "judger.log")

NOBODY_UID = pwd.getpwnam("nobody").pw_uid
NOBODY_GID = grp.getgrnam("nogroup").gr_gid
RETRY_DELAY_SEC = 30

def _load_config():
    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            return yaml.load(f)
    except FileNotFoundError:
        # TODO: no config file
        print("cannot find config file: ./config.yaml")
        exit(1)

def _init_CHECKPOINTIDS():
    tmp = dict()
    for _dir in os.listdir(BASE_DATA_PATH):
        # print(_dir)
        try:
            checkpoint_id, file_type = _dir.split(".")
            if file_type in ["in", "out"]:
                tmp[checkpoint_id] = tmp.get(checkpoint_id, 0) + 1
        except Exception:
            continue
    return dict((int(key), True) for key, value in tmp.items() if value == 2)

CONFIG = _load_config()
CHECKPOINTIDS = _init_CHECKPOINTIDS()

if __name__ == "__main__":
    print(CONFIG)