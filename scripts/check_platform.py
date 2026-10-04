"""Read-only platform report. Does not start the service or process recordings."""

import json
import platform
import shutil
import subprocess
from pathlib import Path


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main():
    system = platform.system()
    report = {
        "system": system,
        "architecture": platform.machine(),
        "kernel": platform.release(),
        "uploads_enabled_by_this_check": False,
        "tools": {name: bool(shutil.which(name)) for name in ("docker", "uv", "s")},
    }
    raw = command(["docker", "info", "--format", "{{json .}}"])
    if raw:
        try:
            info = json.loads(raw)
            report["docker"] = {
                key: info.get(key)
                for key in (
                    "ServerVersion",
                    "Architecture",
                    "OperatingSystem",
                    "KernelVersion",
                    "CgroupVersion",
                )
            }
        except ValueError:
            report["docker"] = "Could not parse Docker metadata"
    if system == "Darwin":
        report["macos_version"] = command(["sw_vers", "-productVersion"])
        report["ram_bytes"] = command(["sysctl", "-n", "hw.memsize"])
        report["swap"] = command(["sysctl", "vm.swapusage"])
        report["compressor_mode"] = command(["sysctl", "-n", "vm.compressor_mode"])
        report["core_limits"] = command(["launchctl", "limit", "core"])
        report["power_settings"] = command(["pmset", "-g", "custom"])
        directory = Path.home() / "Library/Group Containers/group.com.docker"
        for filename in ("settings-store.json", "settings.json"):
            path = directory / filename
            if path.is_file():
                try:
                    settings = json.loads(path.read_text())
                    keys = (
                        "memoryMiB",
                        "swapMiB",
                        "useVirtualizationFramework",
                        "useDockerVmm",
                        "vmType",
                        "useRosetta",
                        "enhancedContainerIsolation",
                    )
                    report["desktop_settings"] = {k: settings[k] for k in keys if k in settings}
                except (OSError, ValueError):
                    report["desktop_settings"] = "Could not read selected settings"
                break
        report["next_step"] = "Mac VM memory protection must be verified before enabling uploads."
    elif system == "Linux" and "microsoft" in platform.release().lower():
        from serve_wsl import guest_problems

        report["wsl_guest_problems"] = guest_problems()
        script = Path(__file__).with_name("windows_guard.ps1")
        windows_path = command(["wslpath", "-w", str(script)])
        if windows_path and shutil.which("powershell.exe"):
            state = command(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    windows_path,
                ]
            )
            if state:
                try:
                    report["windows_guard"] = json.loads(state.lstrip("\ufeff"))
                except ValueError:
                    report["windows_guard"] = "Could not parse host protection report"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
