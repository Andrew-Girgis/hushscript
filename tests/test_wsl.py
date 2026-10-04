import math

import pytest
from provision_tls import provision_pem
from serve_wsl import guest_problems, state_problems

RELEASE = "6.6.87.2-microsoft-standard-WSL2"
SWAPS = "Filename Type Size Used Priority\n"


def test_wsl_refuses_active_dump_collection_even_with_changed_config():
    assert guest_problems(
        release=RELEASE, command_line="init=/init WSL_ENABLE_CRASH_DUMP=1", swaps=SWAPS
    )
    assert not guest_problems(release=RELEASE, command_line="init=/init", swaps=SWAPS)


def test_wsl_refuses_active_or_unknown_swap_state():
    for swaps in ("", SWAPS + "/dev/sdb partition 100 0 -2\n"):
        assert guest_problems(release=RELEASE, command_line="init=/init", swaps=swaps)


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"protected": "true", "updated_at": 100},
        {"protected": True, "updated_at": 90},
        {"protected": True, "updated_at": 103},
        {"protected": True, "updated_at": math.nan},
        {"protected": True, "updated_at": 100, "problems": ["unsafe"]},
    ],
)
def test_windows_guard_must_be_current_and_unambiguously_protected(state):
    assert state_problems(state, now=100)


def test_current_windows_guard_accepts_success_and_preserves_errors():
    assert not state_problems({"protected": True, "updated_at": 100, "problems": []}, now=100)
    assert state_problems(
        {"protected": False, "updated_at": 100, "problems": ["Paging active"]}, now=100
    ) == ["Paging active"]


def test_certificate_transport_keeps_private_material_off_command_line(monkeypatch):
    calls = []
    monkeypatch.setattr("provision_tls.subprocess.run", lambda *a, **kw: calls.append((a, kw)))
    pem = b"-----BEGIN CERTIFICATE-----\nfixture\n-----BEGIN PRIVATE KEY-----\nfixture"
    provision_pem(["docker", "compose"], pem)
    args, options = calls[0]
    assert options["input"] == pem
    assert "fixture" not in str(args)
    assert "env" not in options
    assert "-T" in args[0]


@pytest.mark.parametrize("pem", [None, b"", b"x" * 65537, b"-----BEGIN CERTIFICATE-----"])
def test_invalid_certificate_never_reaches_docker(pem):
    with pytest.raises(ValueError):
        provision_pem(["docker", "compose"], pem)
