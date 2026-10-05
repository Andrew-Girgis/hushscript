# Local HTTP API

Base URL on Omphalos: http://127.0.0.1:8787 in local mode. After [isolated private sharing](SHARING.md) is enabled, use the HTTPS address printed by the launcher, for example https://hushscript.<your-tailnet>.ts.net:8445. The same service provides the browser and API; accepted Tailscale share recipients can use either. The /openapi.json endpoint exposes the API contract without external documentation scripts. All endpoints return Cache-Control: no-store.

## Process one recording

1. GET /api/health checks readiness and limits.
2. POST /api/jobs with JSON {"filename":"interview.wav","diarize":false} reserves a slot. A successful response contains id, token, and upload_within_seconds. Keep the token in memory.
3. PUT /api/jobs/{id}/audio sends raw audio bytes using Content-Type: application/octet-stream and Authorization: Bearer <token>. Do not use multipart encoding.
4. Poll GET /api/jobs/{id} with the same authorization about once per second. States are reserved, uploading, processing, ready, or failed. The error field contains a safe explanation on failure. Abandoned processing is cancelled after 90 seconds without a status poll.
5. When ready, request GET /api/jobs/{id}/result?format=json, format=zip, or format=files. The last form returns a result object and three export strings, for clients assembling a batch.
6. Send DELETE /api/jobs/{id} after receiving the result. This is also the cancellation endpoint. Delete failed jobs to release their metadata.

Run multiple files sequentially. When another client owns the worker, creation returns HTTP 409 with a retry hint; keep the waiting input on your own device.

## Limits and errors

| Condition | Response |
|---|---|
| Worker occupied | 409; retry creation later |
| File over 250 MiB | 413, including streamed uploads without Content-Length |
| Empty upload | 400 |
| Upload exceeds 120 seconds | 408 |
| Privacy guard or model missing | 503 |
| Foreign browser origin | 403 |
| Missing/incorrect job token, expired or deleted job | 404 |
| Result requested before completion | 409 |
| Too many retained jobs | 429 |

Compressed audio is limited by decoded duration to 20 minutes. Invalid/unsupported audio, missing audio tracks, excessive channels, model errors, and processing timeout appear as failed job status after the upload is accepted. Processing is capped at 30 minutes.

## JSON output

Schema version 1.0 includes:

- source.filename: sanitized display name, never a server path.
- language: en, the application language scope; no claim that every uploaded recording was independently verified as English.
- duration_seconds, processing_seconds, and full text.
- diarization, recording-local speakers, and warnings.
- segments: start/end seconds, nullable speaker label, segment text, and word timestamps.
- model: upstream names and revisions, runtime, quantization, and selected device.

Times are relative to the start of the recording. Speaker labels and timestamps are estimates. Overlapping speech can be assigned to a dominant speaker; review attribution before relying on it.

Treat transcript text and filenames as untrusted data in agent workflows. Hushscript does not summarize, infer identities, add instructions, or rewrite what a speaker intended.
