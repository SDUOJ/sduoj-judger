import os
import pwd
import grp
import yaml


CONFIG_FILE_PATH = "config.yaml"


def _load_config():
    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            return yaml.load(f)
    except FileNotFoundError:
        return os.environ

CONFIG = _load_config()

SANDBOX_PATH = CONFIG.get("SANDBOX_PATH", "/usr/bin/sandbox")

BASE_WORKSPACE_PATH = CONFIG.get("BASE_WORKSPACE_PATH", "workspace")
BASE_LOG_PATH = CONFIG.get("BASE_LOG_PATH ", "log")
BASE_DATA_PATH = CONFIG.get("BASE_DATA_PATH ", "data")

SANDBOX_LOG_PATH = CONFIG.get("SANDBOX_LOG_PATH", os.path.join(BASE_LOG_PATH, "sandbox.log"))
JUDGER_LOG_PATH = CONFIG.get("JUDGER_LOG_PATH", os.path.join(BASE_LOG_PATH, "judger.log"))

NOBODY_UID = pwd.getpwnam("nobody").pw_uid
NOBODY_GID = grp.getgrnam("nogroup").gr_gid
RETRY_DELAY_SEC = 10


def _init_CHECKPOINTIDS():
    tmp = dict()
    if not os.path.exists(BASE_DATA_PATH):
        return tmp

    for _dir in os.listdir(BASE_DATA_PATH):
        try:
            checkpoint_id, file_type = _dir.split(".")
            if file_type in ["in", "out"]:
                tmp[checkpoint_id] = tmp.get(checkpoint_id, 0) + 1
        except Exception:
            continue
    return dict((key, True) for key, value in tmp.items() if value == 2)

CHECKPOINTIDS = _init_CHECKPOINTIDS()


if __name__ == "__main__":
    print(CONFIG)
