# Portability status

Docker packages application dependencies. GPU access and host memory handling still depend on the operating system.

| Target | Image design | Current verification |
|---|---|---|
| Native Linux x86-64 CPU | Official native binary, CPU Compose configuration | Image built; transcription, two-speaker labeling, exports, and cleanup passed on Omphalos without GPU access |
| Native Linux x86-64 NVIDIA | CUDA binary, NVIDIA CDI overlay | Image built; actual inference and GPU memory measured on RTX 3070 |
| Native Linux ARM64 CPU | Official aarch64 binary selected through TARGETARCH | Image built; native libraries load and 14 tests pass under ARM64 emulation; no native ARM host run yet |
| Windows / WSL2 | Linux CPU image and local Docker Engine inside WSL2 | CPU launcher implemented; Python logic and PowerShell probe/parser checks pass on Linux; real WSL2 run pending |
| macOS Intel / Apple silicon | Linux CPU image for matching architecture | Read-only host preflight available; host privacy launcher and native Mac run pending; no Apple GPU passthrough claimed |

The current Compose deployment uses native Linux host networking and binds only to loopback. Its socket sandbox prohibits new internet sockets after binding. A coworker with native Linux can follow the README CPU instructions; a modern browser on another OS can use an approved Omphalos deployment after private access is configured.

The [WSL2 launcher](WSL.md) requires Windows paging, hibernation, system/live dumps, and WSL dump collection to be disabled. It checks those conditions and the active guest swap state, and uses HTTPS across the Windows forwarding path. It does not change Windows settings. Windows GPU mode remains unverified.

Docker Desktop's container no-swap settings cover the Linux guest cgroup. They do not establish that the host will never page or snapshot the VM. Host sleep, paging, crash dumps, VM suspend, and snapshots need platform-specific controls. The launcher refuses these unverified environments.

Windows means WSL2 for this project; a native Windows server is not planned. The owner expects to test Pythia later using [MACOS.md](MACOS.md), and does not expect to test Andrews-PC. Mac hosting and actual platform validation remain delivery targets from PLAN.md.
