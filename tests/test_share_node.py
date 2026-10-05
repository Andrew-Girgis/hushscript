"""The dedicated node must have a valid authenticated identity before serving."""

import json
import subprocess

import pytest
from share_node import domain


@pytest.mark.parametrize(
    "state",
    [
        {"BackendState": "NeedsLogin", "Self": {}},
        {"BackendState": "Stopped", "Self": {"DNSName": "hushscript.example.ts.net."}},
        {"BackendState": "Running", "Self": {"DNSName": "localhost"}},
    ],
)
def test_isolated_node_refuses_missing_or_invalid_identity(monkeypatch, state):
    monkeypatch.setattr(
        "share_node.subprocess.check_output", lambda *args, **kwargs: json.dumps(state).encode()
    )
    with pytest.raises(RuntimeError, match="not connected"):
        domain(["docker", "compose"])


def test_isolated_node_refuses_unavailable_daemon(monkeypatch):
    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["tailscale", "status"])

    monkeypatch.setattr("share_node.subprocess.check_output", unavailable)
    with pytest.raises(RuntimeError, match="not connected"):
        domain(["docker", "compose"])


def test_isolated_node_uses_its_own_dns_identity(monkeypatch):
    state = {"BackendState": "Running", "Self": {"DNSName": "hushscript.example.ts.net."}}
    monkeypatch.setattr(
        "share_node.subprocess.check_output", lambda *args, **kwargs: json.dumps(state).encode()
    )
    assert domain(["docker", "compose"]) == "hushscript.example.ts.net"


def test_isolated_launcher_keeps_its_origin_and_refuses_overlapping_app(monkeypatch):
    from types import SimpleNamespace

    from serve import configure_tls

    monkeypatch.setattr("share_node.app_running", lambda: False)
    monkeypatch.setattr("share_node.domain", lambda command: "hushscript.example.ts.net")
    command = ["docker", "compose"]
    name = configure_tls(
        SimpleNamespace(isolated_share=True, tls_domain=None, local_tls=False), command
    )
    assert name == "hushscript.example.ts.net"
    assert command[-1].endswith("compose.isolated.yaml")
    assert (
        __import__("os").environ["HUSHSCRIPT_ORIGINS"] == "https://hushscript.example.ts.net:8445"
    )

    monkeypatch.setattr("share_node.app_running", lambda: True)
    with pytest.raises(SystemExit, match="Stop the current Hushscript launcher"):
        configure_tls(SimpleNamespace(isolated_share=True, tls_domain=None), ["docker", "compose"])
