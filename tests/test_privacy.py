import errno
import json
import os
import subprocess
import sys

from hushscript.privacy import anonymous_file


def test_anonymous_file_has_no_filesystem_path():
    fd = anonymous_file()
    try:
        target = os.readlink(f"/proc/self/fd/{fd}")
        assert target.startswith("/memfd:hushscript-audio")
        assert target.endswith("(deleted)")
    finally:
        os.close(fd)


def test_protected_worker_cannot_network_or_dump():
    script = """
import ctypes,json,resource,socket
from hushscript.privacy import protect_process
protect_process(offline=True)
errors=[]
for family in (socket.AF_INET,socket.AF_INET6):
    try:
        socket.socket(family)
    except OSError as exc:
        errors.append(exc.errno)
print(json.dumps({"errors":errors,"dumpable":ctypes.CDLL(None).prctl(3,0,0,0,0),
                  "core_limit":list(resource.getrlimit(resource.RLIMIT_CORE))}))
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert data == {"errors": [errno.EPERM, errno.EPERM], "dumpable": 0, "core_limit": [0, 0]}
