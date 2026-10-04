"""Copy a Tailscale-managed certificate into container tmpfs without a host key file."""

import argparse
import subprocess

# No audio or transcript passes through this setup helper. Tailscale retains its
# own certificate in its existing system credential store.
INSTALL = """
import os,sys
from pathlib import Path
pem=sys.stdin.buffer.read(65537)
if len(pem)>65536 or b'PRIVATE KEY-----' not in pem or b'BEGIN CERTIFICATE' not in pem:
    raise SystemExit('Invalid TLS bundle')
path=Path('/tmp/hushscript-tls.new')
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
try:
    with os.fdopen(fd,'wb') as stream:
        stream.write(pem)
    path.replace('/tmp/hushscript-tls.pem')
finally:
    path.unlink(missing_ok=True)
"""


def provision(command, domain):
    # Keep PEM off argv, environment, persistent bind mounts, and tool output.
    result = subprocess.run(
        [
            "tailscale",
            "cert",
            "--cert-file",
            "-",
            "--key-file",
            "-",
            "--min-validity",
            "48h",
            domain,
        ],
        stdout=subprocess.PIPE,
        check=True,
        timeout=90,
    )
    subprocess.run(
        [*command, "exec", "-T", "app", "python", "-c", INSTALL],
        input=result.stdout,
        check=True,
        timeout=15,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain")
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    command = ["docker", "compose", "-f", "compose.yaml"]
    if args.gpu:
        command += ["-f", "compose.gpu.yaml"]
    command += ["-f", "compose.tls.yaml"]
    provision(command, args.domain)


if __name__ == "__main__":
    main()
