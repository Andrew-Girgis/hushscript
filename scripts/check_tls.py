"""Check container-side TLS without exposing a Tailscale service."""

import argparse
import http.client
import json
import socket
import ssl
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from provision_tls import INSTALL, certificate

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def credentials(domain):
    if domain:
        yield certificate(domain), ssl.create_default_context(), domain
        return
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
        yield (
            cert.read_bytes() + key.read_bytes(),
            ssl.create_default_context(cadata=cert.read_text()),
            "localhost",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="hushscript:cuda")
    parser.add_argument("--tls-domain", help="Test the actual Tailscale-managed certificate")
    args = parser.parse_args()
    name = "hushscript-tls-check"
    with credentials(args.tls_domain) as (pem, context, domain):
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
            "-e",
            f"HUSHSCRIPT_HOSTS={domain}",
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
                input=pem,
                check=True,
            )
            for _ in range(50):
                connection = http.client.HTTPConnection(domain, 8791, timeout=1)
                try:
                    # Dial only loopback; still verify the real certificate's DNS
                    # name and CA chain using SNI and the system trust store.
                    with socket.create_connection(("127.0.0.1", 8791), timeout=1) as raw:
                        connection.sock = context.wrap_socket(raw, server_hostname=domain)
                        connection.request("GET", "/api/health")
                        response = connection.getresponse()
                        assert response.status == 200
                        assert json.load(response)["ready"]
                    break
                except OSError:
                    time.sleep(0.1)
                finally:
                    connection.close()
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
