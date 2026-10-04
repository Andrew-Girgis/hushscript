"""Explicit online setup only. Runtime never downloads models or executable code."""

import argparse
import hashlib
import io
import platform
import tarfile
import urllib.request
from pathlib import Path

from huggingface_hub import hf_hub_download

VERSION = "0.2.0"
RUNTIMES = {
    ("x86_64", "cpu"): "f396057150f1b774935c7414fd32ebc04195a795a34120d78d8c9ecefa1b7507",
    ("aarch64", "cpu"): "ac50694d4729f9eae390a9851d38f51269d9af9829b535325539090a3b95c787",
    ("x86_64", "cuda"): "aef573fcc6c2c759401d2ed03e5ca9e401ed23b0e38cb852d917080c1e2d4515",
}
MODELS = [
    (
        "nvidia/parakeet-tdt-0.6b-v3",
        "541d1f99c6b0c3cd0b11a95167540bb8edefd82b",
        "parakeet-tdt-0.6b-v3.q8_0.gguf",
    ),
    (
        "nvidia/Nemotron-3-Diarization",
        "f667ed73aee57d40cc39428eb768b4fd87a0a29e",
        "Nemotron-3-Diarization.q8_0.gguf",
    ),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=["cpu", "cuda"], default="cpu")
    ap.add_argument("--arch", default=platform.machine())
    ap.add_argument("--runtime-dir", type=Path, default=Path(".runtime/nemo"))
    ap.add_argument("--models-dir", type=Path, default=Path("models"))
    ap.add_argument("--models-only", action="store_true")
    ap.add_argument("--runtime-only", action="store_true")
    args = ap.parse_args()
    if not args.models_only:
        name = f"nemo-speech-{VERSION}-linux-{args.arch}-{args.backend}.tar.gz"
        expected = RUNTIMES[(args.arch, args.backend)]
        url = f"https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v{VERSION}/{name}"
        print(f"Downloading verified runtime {name}", flush=True)
        data = urllib.request.urlopen(url, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit("Runtime checksum mismatch")
        args.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            # Official binary archives: never install any sample recordings.
            keep = [
                m
                for m in members
                if Path(m.name).suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".mp4"}
            ]
            archive.extractall(args.runtime_dir, members=keep, filter="data")
        print(f"Runtime installed in {args.runtime_dir}", flush=True)
    if not args.runtime_only:
        args.models_dir.mkdir(parents=True, exist_ok=True)
        args.models_dir.chmod(0o755)
        for repo, revision, name in MODELS:
            print(f"Downloading pinned weights: {repo}", flush=True)
            downloaded = hf_hub_download(
                repo_id=repo, revision=revision, filename=name, local_dir=args.models_dir
            )
            Path(downloaded).chmod(0o644)
        print("Models ready; no inference audio was used or downloaded.", flush=True)


if __name__ == "__main__":
    main()
