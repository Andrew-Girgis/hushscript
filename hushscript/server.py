"""Bind the HTTP listener before forbidding new IPv4/IPv6 sockets."""

import argparse
import socket
import time
from pathlib import Path

import uvicorn

from .privacy import protect_process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--tls-pem", type=Path, help="One-use PEM on protected tmpfs")
    args = parser.parse_args()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", args.port))
    listener.listen(128)
    listener.setblocking(False)
    protect_process(offline=True)
    if args.tls_pem:
        deadline = time.monotonic() + 120
        while not args.tls_pem.exists():
            if time.monotonic() >= deadline:
                raise SystemExit("TLS certificate was not provisioned.")
            time.sleep(0.1)
    config = uvicorn.Config(
        "hushscript.app:app",
        access_log=False,
        proxy_headers=False,
        log_level="warning",
        limit_concurrency=16,
        timeout_keep_alive=5,
        ssl_certfile=str(args.tls_pem) if args.tls_pem else None,
    )
    try:
        config.load()
    finally:
        if args.tls_pem:
            args.tls_pem.unlink(missing_ok=True)
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
