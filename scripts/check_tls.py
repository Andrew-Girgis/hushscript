"""Check container-side TLS using a throwaway certificate on tmpfs."""

import argparse
import json
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from provision_tls import INSTALL

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="hushscript:cuda")
    args = parser.parse_args()
    name = "hushscript-tls-check"
    with tempfile.TemporaryDirectory(prefix="hushscript-tls-", dir="/dev/shm") as directory:
        cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        context = ssl.create_default_context(cadata=cert.read_text())
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "host",
            "--read-only",
            "--memory",
            "2g",
            "--memory-swap",
            "2g",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16777216",
            "--ulimit",
            "core=0",
            "--log-driver",
            "none",
            "-v",
            f"{ROOT / 'models'}:/models:ro",
            "-v",
            f"{ROOT / '.runtime/host-guard'}:/host-guard:ro",
            args.image,
            "python",
            "-m",
            "hushscript.server",
            "--port",
            "8791",
            "--tls-pem",
            "/tmp/hushscript-tls.pem",
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        try:
            subprocess.run(
                ["docker", "exec", "-i", name, "python", "-c", INSTALL],
                input=cert.read_bytes() + key.read_bytes(),
                check=True,
            )
            for _ in range(50):
                try:
                    with urllib.request.urlopen(
                        "https://127.0.0.1:8791/api/health", context=context, timeout=1
                    ) as response:
                        assert json.load(response)["ready"]
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("TLS service did not become ready")
            subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "python",
                    "-c",
                    "from pathlib import Path; assert not Path('/tmp/hushscript-tls.pem').exists()",
                ],
                check=True,
            )
            print("TLS verified: trusted handshake, healthy app, temporary PEM removed.")
        finally:
            subprocess.run(
                ["docker", "stop", "-t", "3", name], check=True, stdout=subprocess.DEVNULL
            )


if __name__ == "__main__":
    main()
