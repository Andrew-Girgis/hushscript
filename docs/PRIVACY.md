# Privacy design and boundaries

## Data lifecycle

1. The browser reserves one worker slot. Files waiting in its queue remain on the uploader's device.
2. The server streams the selected raw request body into an anonymous Linux memfd; no multipart upload parser or disk spool is used.
3. A fresh child process decodes audio to mono float32 at 16 kHz in memory. A 20-minute decoded-duration limit bounds compressed inputs.
4. Transcription uses windows of at most 44 seconds, including overlapping context, to bound model working memory. Optional diarization uses one continuous recording-wide stream so speaker identities persist across transcription windows.
5. The worker releases model allocations, clears its primary sample array, and exits before the result becomes ready. Its anonymous audio descriptor closes after decoding.
6. The browser fetches result files into memory, acknowledges receipt with DELETE, and builds the batch ZIP locally. The API retains unacknowledged results for at most 15 minutes.
7. Cancellation, upload timeout, abandoned processing, model failure, host-guard loss, and service shutdown clean up jobs. Completed results are also discarded if host protection is lost.

A browser download request is not proof that the user saved the ZIP successfully. The UI retains fetched transcripts in the current tab until cleared or closed. Check the download before clearing.

## Server protections

- Unprivileged UID, read-only root filesystem, read-only model mounts, dropped capabilities, no privilege escalation.
- Readiness rejects a loaded kernel crash dumper and any missing or unreadable crash-dumper status.
- Container memory limit equals memory-plus-swap limit; readiness verifies memory.swap.max=0.
- Small tmpfs for library scratch space, no audio paths or result volume.
- Core limits and PR_SET_DUMPABLE=0 for the app and worker. The latter also addresses hosts using a piped core-dump handler.
- The server binds its listener first, then seccomp denies new IPv4/IPv6 sockets in both the web process and worker. Accepted client connections continue to work. The listener binds directly to host loopback in the native Linux network namespace. There is no Docker userland forwarding process handling plaintext.
- No request access logs; Docker logging disabled; native diagnostic output discarded.
- Explicitly disabled framework telemetry and Hugging Face telemetry; no inference-time downloads.
- Same-origin browser requests, host allowlist, no caching, local assets, and strict script policy.
- Random per-job capability tokens are held in memory and compared by hash. URLs do not contain those tokens.

## Host protection

Anonymous memory can otherwise reach disk through swap, crash dumps, hibernation, VM snapshots, or driver memory-preservation features. Docker alone cannot verify every host mechanism.

The native Linux launcher verifies a local cgroup-v2 engine and acquires a blocking logind sleep/shutdown inhibitor. An independent helper retains that inhibitor until the app container stops, including when the launcher is killed. A periodically renewed guard record contains only protection status and a timestamp, never audio or transcript data. The app refuses new work without a current guard and disposes of existing jobs when the guard expires.

The [WSL2 launcher](WSL.md) also checks Windows paging, hibernation, system/live crash dumps, WSL crash-dump collection, and guest swap. A separate Windows helper retains an idle-sleep request until Docker stops. This path is implemented but has not been exercised on a real Windows host. TLS terminates in the container so the Windows forwarding path handles ciphertext. macOS hosting remains disabled until host VM protections are established; [MACOS.md](MACOS.md) provides a read-only check.

The native Linux launcher does not change global sleep or swap settings. It inhibits normal sleep while the service runs. An administrator forcing suspend, altering the guard, changing Docker controls, attaching a debugger, enabling packet capture, or making machine snapshots is outside this boundary.

## Scope of the promise

The service does not intentionally persist uploaded audio or server-held transcripts. It releases allocations and file descriptors after use. Python, codecs, GPU runtimes, drivers, and the kernel can make transient copies; this is not a forensic zeroization guarantee for physical RAM or VRAM.

The uploader's original files, their browser and operating system, and intentionally downloaded transcript exports remain under that device owner's control. If the uploader's browser runs on the server machine, its original files are still outside Hushscript's server cleanup.

A public source repository does not receive inputs or outputs. Setup may contact package registries, GitHub, and Hugging Face to obtain dependencies and models. Inference remains local.

Tailscale coordination and encrypted relay use were explicitly accepted for remote access. Remote mode terminates TLS inside this same protected web process. A one-use certificate bundle is piped from Tailscale's existing credential store into container tmpfs, loaded, and unlinked. The isolated Tailscale sidecar uses raw TCP forwarding, so it handles only TLS ciphertext. It shares a network namespace with the protected app but publishes no host ports. Its persistent Docker volume holds only Tailscale identity state, never audio. See SHARING.md for login and invitation steps.
