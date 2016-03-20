import os
from rackattack.virtual.kvm import config
if __name__ == "__main__":
    if os.path.exists(config.PID_FILEPATH):
        os.unlink(config.PID_FILEPATH)
