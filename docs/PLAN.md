# Hushscript v1 — agreed scope

- Public MIT repository: Andrew-Girgis/hushscript; model licenses remain separate.
- Linux, Windows through WSL2, and macOS portability targets; x86-64 and ARM64 CPU images; NVIDIA acceleration where supported. Record actual verification separately from targets.
- Browser uploader and local HTTP API. English, two-person 5–10 minute interviews.
- Optional diarization, off by default; recording-scoped anonymous labels.
- Up to 50 files per batch, 250 MiB and 20 minutes per file; one server job at a time. Waiting files stay on the uploader's device.
- Plain text, Markdown, and versioned timestamped JSON exports in a ZIP bundle.
- Uploaded audio never persisted. No disk spooling, content logs, telemetry, model training, cloud inference, or runtime model downloads. Clean up on success, cancellation, timeout, disconnect, or failure.
- Server results are memory-only; purge after acknowledged receipt or 15 minutes. Browser can assemble a batch bundle after receiving each result.
- Inspect swap, crash dumps, sleep/hibernation, GPU memory preservation, and proxy handling. Fail closed when required protections are absent. No claim of forensic erasure of transient physical memory; uploader's original files are outside server retention.
- Tailscale Serve is permitted for private networking (hosted coordination and encrypted relay accepted). Share only Omphalos with the coworker through a single-use external machine invite, and restrict the shared recipient to Hushscript port 8445 using the full tailnet policy. The owner's existing access stays intact. No Funnel or public password endpoint.
- Evaluate Parakeet v3 and Nemotron 3 diarization, compare transcription with faster-whisper locally. Pin selected model artifacts and measure correctness, latency, and memory.
- Tests must cover limits, cancellation, malformed/silent audio, cleanup, result isolation, offline operation, and an actual model transcription.

## Initial readiness evidence

Omphalos: i9-9900K (8 cores/16 threads), 32 GB RAM, RTX 3070 8 GB. Docker/Compose and NVIDIA Container Toolkit installed. GitHub account Andrew-Girgis authenticated; target repo absent. Tailscale running.

Host has disk swap and hibernation configured. NVIDIA PreserveVideoMemoryAllocations=1 uses /var/tmp. A host sleep inhibitor is required during protected processing; container restrictions alone cannot cover this.

## Platform testing decision

Windows hosting targets WSL2; no native Windows service is planned. The owner does not expect to test Andrews-PC, so keep WSL runtime validation explicitly pending. Pythia testing will be done by the owner when home. Prepare a read-only Mac report and container compatibility check; do not connect to either machine without authorization.
