"""Hold systemd's inherited inhibitor until the protected container stops."""

import subprocess
import sys
import time

# No recording or transcript is passed through this helper.
sys.stdin.read()
command = sys.argv[1:]
while True:
    result = subprocess.run([*command, "stop", "-t", "3"], check=False)
    if result.returncode == 0:
        break
    print("Hushscript could not stop Docker; retaining the sleep inhibitor.", file=sys.stderr)
    time.sleep(2)
