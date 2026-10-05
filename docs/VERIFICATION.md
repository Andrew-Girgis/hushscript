# Verification record

Verified locally on 2026-10-04 and 2026-10-05. Host: Omphalos, i9-9900K, 32 GiB RAM, RTX 3070 8 GiB. Audio fixtures were downloaded into protected memory; no recordings or full transcripts are committed or retained as artifacts.

## Automated checks

- All 61 service/privacy/chunking/codec/launcher/node tests passed locally and inside the read-only, network-isolated, non-root Docker test container with swap disabled.
- Seven codec round trips cover WAV/PCM, MP3, M4A/AAC, FLAC, OGG/Opus, AAC/ADTS, and WebM/Opus.
- Browser acceptance passed: sequential uploads, cleanup ACK before the next upload, speaker toggle, safe filename display, ZIP CRC/readability, cancellation, batch/size bounds, and mobile layout. Browser inference responses are simulated.
- Actual CPU and GPU API checks passed: public speech, silence, malformed data, two-speaker labeling, JSON/ZIP exports, and DELETE followed by 404.
- Active GPU inference cancellation completed in 0.004 seconds in one run. An interrupted upload was removed and the worker slot was reusable.
- Host guard expiry was tested by pausing only the launcher heartbeat while the independent sleep inhibitor remained active. Upload creation returned 503, the reserved job disappeared, and the service recovered when the launcher resumed.
- Container TLS passed trusted handshakes and health checks with both a throwaway localhost certificate and an actual Tailscale-managed certificate. The test dialed loopback, verified the real DNS name and CA chain, and confirmed the one-use PEM was removed after loading.
- Worker restrictions deny new IPv4/IPv6 sockets and disable dumps. The live app accepts its inherited listener under the same socket restriction.
- Six WSL launcher lifecycle cases pass with simulated Windows/Docker boundaries: rejected protection, Docker startup failure, certificate failure, guard exit, guard loss, and normal shutdown. They verify guard revocation and the stop request before helper release, without contacting a Windows machine.
- The isolated Tailscale sidecar first passed an unauthenticated throwaway-container check with a read-only root and no published host ports. On Omphalos, the authenticated `hushscript` node now has a single raw TCP Serve route, 8445 to app port 8787. The GPU app shares its network namespace, has a read-only root, and publishes no host port. Omphalos's original Serve routes on 443, 8443, and 8444 were unchanged. The trusted private URL returned the browser page and GPU health response; an in-memory one-second WAV completed the API job, returned JSON, and was deleted with HTTP 204. Coworker-device access has not yet been tested.
- Seven isolated-node checks reject missing, stopped, or invalid Tailscale identities.
- Windows guard parser, mocked fail-closed probes, and C# power-helper compilation pass in a Linux PowerShell container. These checks do not exercise Windows registry/WMI/power APIs or WSL interop.
- Linux ARM64 test image builds; both ASR and diarization library entry points load under ARM64 emulation. All 14 chunking/format/codec tests pass there. No native ARM host or Mac inference is claimed.
- Kernel crash-dumper checks reject loaded, unreadable, and invalid states.
- CPU and CUDA images build. The stale NVIDIA CDI UVM mapping was refreshed; actual GPU model loading now succeeds.

## Model comparison

One run per configuration on the same 11-second public JFK fixture. Timing includes model loading and inference, excludes network download and decoding, and is not a cold-disk benchmark. Word error rate ignores punctuation/case. This tiny sample does not establish general interview accuracy.

| Engine | Device | Seconds | Word error rate | Peak process RAM MiB | Approx. additional GPU MiB |
|---|---|---:|---:|---:|---:|
| Parakeet Q8_0 | RTX 3070 | 0.357 | 0 | 270.1 | 965.1 |
| faster-whisper turbo, int8_float16 | RTX 3070 | 3.922 | 0 | 1767.1 | 1265.1 |
| Parakeet Q8_0 | CPU, 6 cores | 1.679 | 0 | 837.9 | — |
| faster-whisper turbo, int8 | CPU, 6 cores | 5.478 | 0 | 2236.1 | — |

GPU memory is sampled device-wide above a pre-run baseline and can include unrelated desktop changes. CPU Parakeet was measured with the CPU runtime image; the CUDA runtime depends on the driver even when selecting CPU.

The comparison model is dropbox-dash/faster-whisper-large-v3-turbo at revision 0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf. It is an optional benchmark download, not an application dependency.

## Actual API observations

These times include worker startup and decoding but exclude upload time.

| Fixture | Duration | GPU seconds | CPU seconds | Result |
|---|---:|---:|---:|---|
| Public JFK | 11 s | 0.657 | 1.195 | Expected reference phrase; 22 timestamped words |
| Generated silence | 1 s | 0.292 | 0.301 | Empty transcript |
| Public AMI meeting | 60 s | 1.128 | 7.151 | Three labels against a four-speaker reference; review attribution |
| Constructed two-speaker AMI excerpts | 80 s | 1.252 | 9.735 | Two labels across multiple ASR windows |
| Repeated public JFK | 600 s | 2.527 | Not run | Completed with timestamps covering the end |

The repeated ten-minute clip is a bounded-processing smoke check, not a representative interview benchmark. The constructed two-speaker clip is also not an accuracy evaluation. No diarization error rate has been established.

After an earlier long GPU suite, the app cgroup reported a 489.9 MiB memory peak and zero swap usage. Container working-set memory and the benchmark process RSS are different measurements.

## Remaining delivery work

- Invite the approved coworker to the dedicated `hushscript` node and test browser/API access from their device. The owner-side private route and certificate have passed end-to-end checks.
- Actual WSL2 startup/cleanup verification, protected macOS hosting, and native ARM host inference. WSL2 CPU code and Mac preflight instructions are present; user-led Pythia testing is planned.
- Evaluation on representative interview recordings for transcription and speaker accuracy.

The server result TTL is tested with a shortened clock interval in automated tests; a full fifteen-minute wall-clock run was not required. Shutdown and process cleanup have automated coverage; no forced host sleep or power-loss test was performed.

## Reproduce

Use the README commands for unit, container, and browser checks. Run scripts/check_inference.py and scripts/check_runtime.py inside a read-only, no-swap container while the real host guard is active; bind the script into /app and the guard into /host-guard, and use host networking to reach the loopback service. The inference script accepts --long and --base-url.

scripts/benchmark.py uses only an in-memory public fixture, verifies the guard/swap settings, and disables networking before model inference. Build the benchmark Docker target for faster-whisper dependencies. CPU Parakeet can run using the normal CPU image with the script bind-mounted into /app.

scripts/check_tls.py creates an isolated temporary container and a throwaway certificate in host tmpfs, then removes both. Its --tls-domain option instead exercises an actual Tailscale-managed certificate without exposing a remote service. No recordings are involved.

The PowerShell parser/probe checks are in scripts/check_windows_guard.ps1. The WSL and Mac guides describe platform prerequisites and remaining real-host checks.
