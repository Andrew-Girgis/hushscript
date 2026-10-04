"""Create a localhost certificate; keep its private key only in the s encrypted store."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not (ROOT / ".senv").exists():
        raise SystemExit("Run s init from the project first to create its encrypted secret store.")
    if not Path("/dev/shm").is_dir():
        raise SystemExit("Run this setup inside Linux/WSL; it requires a RAM filesystem.")
    with (
        tempfile.TemporaryFile(dir="/dev/shm") as key,
        tempfile.TemporaryFile(dir="/dev/shm") as cert,
    ):
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:3072",
                "-days",
                "30",
                "-subj",
                "/CN=Hushscript localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                f"/proc/self/fd/{key.fileno()}",
                "-out",
                f"/proc/self/fd/{cert.fileno()}",
            ],
            pass_fds=(key.fileno(), cert.fileno()),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cert.seek(0)
        key.seek(0)
        public = cert.read()
        subprocess.run(
            ["s", "set", "HUSHSCRIPT_TLS_PEM", "--stdin"],
            input=public + key.read(),
            check=True,
            cwd=ROOT,
            env={**os.environ, "S_FILE": str(ROOT / ".senv")},
        )
    directory = ROOT / ".runtime/tls"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "localhost.crt"
    output.write_bytes(public)
    output.chmod(0o644)
    print(f"Public certificate: {output}")
    subprocess.run(
        ["openssl", "x509", "-in", str(output), "-noout", "-fingerprint", "-sha256"], check=True
    )
    print("Trust only this public certificate on the client. The private key is in s.")
    print("Start: s HUSHSCRIPT_TLS_PEM -- python3 scripts/serve.py --local-tls")


if __name__ == "__main__":
    main()
