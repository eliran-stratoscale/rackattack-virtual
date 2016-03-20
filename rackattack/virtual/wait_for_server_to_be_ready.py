import os
import re
import sys
import time
import argparse
import subprocess
from rackattack.virtual.kvm import config


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serverListeningPort", default=config.DEFAULT_REQUEST_PORT, type=int)
    args = parser.parse_args()
    while True:
        print "Waiting for PID file of Rackattack at %s..." % (config.PID_FILEPATH,)
        if os.path.exists(config.PID_FILEPATH):
            break
        time.sleep(1)
    print "Reading PID file..."
    with open(config.PID_FILEPATH) as pidFile:
        pid = pidFile.read()
    while True:
        print "Waiting for server process (pid: %(pid)s) to start listening on port %(port)s..." \
            % dict(port=args.serverListeningPort, pid=pid)
        cmd = ["netstat", "-putan"]
        out = subprocess.check_output(cmd, stderr=sys.stdout)
        pattern = ":%(port)s +[:*.0-9]+ +\D+%(pid)s\/.+" % dict(port=args.serverListeningPort, pid=pid)
        result = re.findall(pattern, out)
        if result:
            break
    print "Rackattack is ready."
