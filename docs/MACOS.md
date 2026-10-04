# macOS verification on Pythia

The Linux ARM64 CPU image builds and its native libraries load under ARM64 emulation. Fourteen chunking/export/codec tests pass under emulation. This does not establish native Mac inference or safe handling of a Docker VM's memory.

Mac hosting remains incomplete: the launcher refuses macOS until host paging, hibernation, crash dumps, VM suspend, and snapshots can be covered. Docker's guest no-swap limit does not prove that macOS cannot page the VM. No Apple GPU acceleration is claimed. A Mac browser can use an approved Omphalos deployment after private sharing is configured.

## Run when home

With Python 3 available, clone or update the repository on Pythia and run:

~~~bash
git clone https://github.com/Andrew-Girgis/hushscript.git
cd hushscript
python3 scripts/check_platform.py
~~~

For an existing clone, use git pull --ff-only instead of cloning again. Docker may be stopped or absent; the report records what it can inspect. It prints the architecture, OS version, RAM/swap and power settings, core limits, Docker engine details, and a small allowlist of Docker Desktop settings. It neither changes host settings nor enables uploads, and it does not inspect audio or credentials.

Share that report to determine the remaining host controls. Do not upload private recordings or create a fake host-guard file to bypass readiness. There is no need to disable SIP or change global swap settings for this check.

## Optional container compatibility check

With Docker running, this command sequence builds the CPU test image for the Mac's architecture and runs synthetic tests. It downloads dependencies but does not download recordings or model weights:

~~~bash
docker build --target test -t hushscript:test .
docker run --rm --network none --read-only --memory 2g --memory-swap 2g \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=67108864 --ulimit core=0 hushscript:test
~~~

A passing suite verifies container compatibility, not the Mac host privacy requirements. Native inference and a protected Mac launcher still require additional work after the host report.
