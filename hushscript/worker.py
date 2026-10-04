"""One protected process per recording. stdout is an internal result pipe."""

import argparse
import json
import os
import sys
import time

from .privacy import protect_process


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", type=int, required=True)
    parser.add_argument("--diarize", action="store_true")
    args = parser.parse_args()
    protect_process(child=True, offline=True)
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "PYANNOTE_METRICS_ENABLED": "0",
            "DO_NOT_TRACK": "1",
        }
    )
    saved_stdout = os.dup(1)
    os.dup2(2, 1)
    samples = None

    class AudioError(Exception):
        pass

    started = time.monotonic()
    try:
        import numpy as np

        from .audio import AudioError, decode
        from .exports import segments_from_words
        from .native import transcribe

        samples = decode(args.fd)
        os.close(args.fd)
        duration = len(samples) / 16000
        warnings = []
        if float(np.max(np.abs(samples))) < 0.0001:
            text, words = "", []
            warnings.append("No audible speech was detected.")
        else:
            text, words = transcribe(
                samples,
                runtime_dir=os.environ["HUSHSCRIPT_RUNTIME"],
                model_dir=os.environ["HUSHSCRIPT_MODELS"],
                device=os.environ.get("HUSHSCRIPT_DEVICE", "cpu"),
                diarize=args.diarize,
            )
            if not text.strip():
                warnings.append("No speech was recognized.")
        speakers = sorted({word["speaker"] for word in words if word["speaker"]})
        if args.diarize:
            warnings.append("Speaker labels are estimates and apply only to this recording.")
            if len(speakers) != 2 and words:
                warnings.append(f"Detected {len(speakers)} speaker labels; review attribution.")
        output = {
            "schema_version": "1.0",
            "language": "en",
            "duration_seconds": round(duration, 3),
            "text": text,
            "diarization": args.diarize,
            "speakers": speakers,
            "segments": segments_from_words(words),
            "warnings": warnings,
            "model": {
                "transcription": "nvidia/parakeet-tdt-0.6b-v3",
                "revision": "541d1f99c6b0c3cd0b11a95167540bb8edefd82b",
                "diarization": "nvidia/Nemotron-3-Diarization" if args.diarize else None,
                "diarization_revision": "f667ed73aee57d40cc39428eb768b4fd87a0a29e"
                if args.diarize
                else None,
                "runtime": "NeMo-Speech.cpp 0.2.0",
                "quantization": "Q8_0",
                "device": os.environ.get("HUSHSCRIPT_DEVICE", "cpu"),
            },
            "processing_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        safe = (
            str(exc) if isinstance(exc, (AudioError, RuntimeError)) else "Local processing failed."
        )
        output = {"error": safe}
    finally:
        if samples is not None:
            samples.fill(0)
        os.dup2(saved_stdout, 1)
        os.close(saved_stdout)
    sys.stdout.write(json.dumps(output, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
