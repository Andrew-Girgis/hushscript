"""Process protections complement, never replace, host protections."""

import ctypes
import errno
import json
import os
import resource
import signal
import socket
import time
from pathlib import Path


def protect_process(*, child=False, offline=False):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0:
        raise RuntimeError("Cannot disable process dumps")
    if child and libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise RuntimeError("Cannot establish worker lifetime")
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError("Cannot restrict process privileges")
    if offline:
        deny_network()


def deny_network():
    """Deny new IPv4/IPv6 sockets in this process and all descendants."""

    class Arg(ctypes.Structure):
        _fields_ = [
            ("arg", ctypes.c_uint),
            ("op", ctypes.c_int),
            ("a", ctypes.c_uint64),
            ("b", ctypes.c_uint64),
        ]

    sec = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    sec.seccomp_init.argtypes = [ctypes.c_uint32]
    sec.seccomp_init.restype = ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    sec.seccomp_syscall_resolve_name.restype = ctypes.c_int
    sec.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(Arg),
    ]
    sec.seccomp_load.argtypes = [ctypes.c_void_p]
    sec.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = sec.seccomp_init(0x7FFF0000)
    if not ctx:
        raise RuntimeError("Cannot create network sandbox")
    try:
        syscall = sec.seccomp_syscall_resolve_name(b"socket")
        for family in (socket.AF_INET, socket.AF_INET6):
            arg = Arg(0, 4, family, 0)
            if sec.seccomp_rule_add_array(
                ctx, 0x00050000 | errno.EPERM, syscall, 1, ctypes.byref(arg)
            ):
                raise RuntimeError("Cannot restrict worker networking")
        if sec.seccomp_load(ctx):
            raise RuntimeError("Cannot activate worker network sandbox")
    finally:
        sec.seccomp_release(ctx)


def readiness(model_dir, runtime_dir, guard_path):
    errors = []
    try:
        if Path("/sys/fs/cgroup/memory.swap.max").read_text().strip() != "0":
            errors.append("Container swap is not disabled.")
    except OSError:
        errors.append("Cannot verify cgroup v2 swap protection.")
    try:
        guard = json.loads(Path(guard_path).read_text())
        age = time.time() - guard["updated_at"]
        if age < -2 or age > 8 or not guard.get("protected"):
            errors.append("Host privacy guard is not active.")
    except (OSError, ValueError, KeyError, TypeError):
        errors.append("Start with the host privacy launcher.")
    if not (Path(model_dir) / "parakeet-tdt-0.6b-v3.q8_0.gguf").is_file():
        errors.append("Download the transcription model during setup.")
    if not (Path(runtime_dir) / "lib/libnemo_speech_asr_c.so.1").is_file():
        errors.append("Native inference runtime is missing.")
    return errors


def anonymous_file(name="hushscript-audio"):
    """Use Linux memfd even when a standalone Python build omits os.memfd_create."""
    if hasattr(os, "memfd_create"):
        return os.memfd_create(name, os.MFD_CLOEXEC)
    libc = ctypes.CDLL(None, use_errno=True)
    create = libc.memfd_create
    create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    create.restype = ctypes.c_int
    fd = create(name.encode(), 1)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "Cannot create anonymous audio buffer")
    return fd
