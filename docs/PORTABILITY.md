# Portability status

Docker packages application dependencies. GPU access and host memory handling still depend on the operating system.

| Target | Image design | Current verification |
|---|---|---|
| Native Linux x86-64 CPU | Official native binary, CPU Compose configuration | Image built; transcription, two-speaker labeling, exports, and cleanup passed on Omphalos without GPU access |
| Native Linux x86-64 NVIDIA | CUDA binary, NVIDIA CDI overlay | Image built; actual inference and GPU memory measured on RTX 3070 |
| Native Linux ARM64 CPU | Official aarch64 binary selected through TARGETARCH | Build/run not verified on ARM64 |
| Windows / WSL2 | Linux CPU image; GPU depends on supported drivers | Host privacy launcher not implemented or verified |
| macOS Intel / Apple silicon | Linux CPU image for matching architecture | Host privacy launcher not implemented or verified; no Apple GPU passthrough claimed |

The current Compose deployment uses native Linux host networking and binds only to loopback. Its socket sandbox prohibits new internet sockets after binding. A coworker with native Linux can follow the README CPU instructions; a modern browser on another OS can use an approved Omphalos deployment after private access is configured.

Docker Desktop's container no-swap settings cover the Linux guest cgroup. They do not establish that the host will never page or snapshot the VM. Host sleep, paging, crash dumps, VM suspend, and snapshots need platform-specific controls. The launcher refuses these unverified environments.

Windows/macOS launchers and ARM64 verification remain delivery targets from PLAN.md. This record does not claim they are complete.
