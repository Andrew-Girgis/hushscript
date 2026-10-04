# Windows hosting through WSL2

The CPU launcher is implemented for Docker Engine inside a WSL2 distribution. Python checks and PowerShell parser/probe checks pass on Linux; the complete launcher has **not been run on Windows**. Windows GPU mode and Docker Desktop hosting are not verified. Do not treat these checks as a tested Windows deployment.

## Host prerequisites

Use a current WSL2 distribution with systemd, cgroup v2, Python 3.12+, uv, OpenSSL, and Docker Engine with Compose installed inside that distribution. [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/) cover the engine installation. Keep the clone in the Linux filesystem. The launcher and its cleanup helper use the same Linux user and the local socket at /var/run/docker.sock; that user must be able to run Docker without an interactive sudo prompt.

The no-persistence requirement also applies to Windows memory backing the WSL VM. The guard checks all of the following:

| Windows setting | Required state |
|---|---|
| Active page files, queried through Win32_PageFileUsage | None, even if current usage is zero |
| HKLM\SYSTEM\CurrentControlSet\Control\Power: HibernateEnabled | DWORD 0 |
| HKLM\SYSTEM\CurrentControlSet\Control\CrashControl: CrashDumpEnabled | DWORD 0 |
| HKLM\SYSTEM\CurrentControlSet\Control\CrashControl\FullLiveKernelReports: FullLiveReportsMax | DWORD 0 |
| WSL crash-dump collection | Disabled in configuration and absent from the running VM command line |
| WSL swap | No active swap entries |

These are host-wide prerequisites, not changes Hushscript applies. Disabling page files reduces available committed memory; disabling hibernation and dumps removes those Windows capabilities. Have the machine owner configure them deliberately and reboot before testing. Missing or unreadable values cause the launcher to refuse startup.

Merge these settings into the existing [wsl2] section of %USERPROFILE%\.wslconfig in Windows:

~~~ini
[wsl2]
swap=0
maxCrashDumpCount=-1
~~~

Save work in every WSL distribution, then run this in Windows PowerShell:

~~~powershell
wsl --shutdown
~~~

This stops all WSL distributions. Relaunch your distribution afterward. The launcher checks the running kernel command line as well as the configuration, so merely editing the file is insufficient.

The negative dump count follows the current [WSL implementation](https://github.com/microsoft/WSL/blob/master/src/windows/service/exe/WslCoreVm.cpp): nonnegative counts enable collection. A value of zero does not disable it. See also [WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) and Microsoft's [live kernel dump controls](https://learn.microsoft.com/en-us/windows/win32/wer/wer-settings).

## Prepare the application

Inside WSL:

~~~bash
git clone https://github.com/Andrew-Girgis/hushscript.git
cd hushscript
uv sync
uv run python scripts/bootstrap.py --models-only
docker compose build
python3 scripts/check_platform.py
~~~

Resolve any reported host or guest protection problems before starting. This report does not enable uploads. The app also independently verifies its container swap limit and that no kernel crash dumper is loaded. An unreadable check disables uploads.

## Local HTTPS

WSL's Windows forwarding path must carry encrypted traffic. Hushscript terminates HTTPS inside its protected container and requires TLS mode on WSL. Install the [s encrypted secret store](https://github.com/tobi/s) inside WSL, then:

~~~bash
s init
python3 scripts/create_local_tls.py
~~~

If this clone already has a Git pre-commit hook, preserve its checks when initializing s. The helper generates a 30-day localhost certificate, puts its private key in the encrypted project store, and writes only the public certificate to .runtime/tls/localhost.crt. It prints the public certificate's SHA-256 fingerprint. Never commit the store or copy its key into an environment file.

On Windows, inspect the public certificate and verify that fingerprint before trusting it for the current user. To find the certificate's Windows path, run inside WSL:

~~~bash
wslpath -w "$PWD/.runtime/tls/localhost.crt"
~~~

In Windows PowerShell, replacing the placeholder with that exact path:

~~~powershell
Import-Certificate -FilePath 'PUBLIC_CERTIFICATE_PATH' -CertStoreLocation Cert:\CurrentUser\Root
~~~

Only import the public certificate you generated and verified. Renew it by rerunning the helper, trusting the replacement, and restarting the service before expiry; remove the old trust entry afterward. Do not bypass browser certificate warnings.

Start inside WSL:

~~~bash
s HUSHSCRIPT_TLS_PEM -- python3 scripts/serve.py --local-tls
~~~

Visit https://localhost:8787 from Windows and leave the launcher open. The private key is removed from the launcher's inherited environment before Docker commands run, delivered to container RAM through stdin, and unlinked after the server loads it. Ctrl+C stops the container and releases its held data.

## Verification and limits

For a first real WSL test, confirm that /api/health reports ready, transcribe a short disposable recording, download the ZIP, cancel a second job, and stop the launcher. Confirm the container stops. Then test that an unmet prerequisite prevents startup. Do not change host protections while private audio is being processed.

A separate Windows process holds an idle-sleep power request, checks host protections every two seconds, and stops Docker before releasing that request when the launcher exits. The app rejects new work and clears jobs when its protection heartbeat expires. Windows [SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate) cannot block deliberate user-initiated sleep. With hibernation disabled, that limitation does not authorize saving VM memory to disk. Forced snapshots, debugger captures, and administrator overrides remain outside the service boundary.

Private coworker access still requires the device policy in [SHARING.md](SHARING.md). Local certificate trust does not grant remote access or open a public port.
