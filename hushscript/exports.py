"""Literal transcript exports; no summaries or agent instructions."""

import html
import io
import json
import re
import zipfile


def clean_name(name):
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    return name[:160] or "recording"


def timestamp(seconds):
    value = max(0, int(seconds))
    return f"{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}"


def segments_from_words(words):
    segments = []
    for word in words:
        if (
            not segments
            or word["speaker"] != segments[-1]["speaker"]
            or word["start"] - segments[-1]["end"] > 1.5
            or len(segments[-1]["words"]) >= 40
        ):
            segments.append(
                {
                    "start": word["start"],
                    "end": word["end"],
                    "speaker": word["speaker"],
                    "text": "",
                    "words": [],
                }
            )
        segment = segments[-1]
        segment["words"].append(word)
        segment["end"] = word["end"]
        segment["text"] = " ".join(w["text"] for w in segment["words"]).strip()
    return segments


def render(result):
    rows = []
    for segment in result["segments"]:
        speaker = segment["speaker"]
        label = speaker.replace("_", " ").title() + ": " if speaker else ""
        rows.append(f"[{timestamp(segment['start'])}] {label}{segment['text']}")
    plain = "\n\n".join(rows) if rows else result["text"]

    def escape(value):
        return re.sub(r"([\\\x60*{}\[\]()#+.!_|>~-])", r"\\\1", html.escape(value))

    markdown = "# Transcript\n\n"
    markdown += f"Source: {escape(result['source']['filename'])}\n\n"
    markdown += "\n\n".join(escape(row) for row in rows) if rows else escape(result["text"])
    if result["warnings"]:
        markdown += "\n\n## Review notes\n\n" + "\n".join(
            "- " + escape(note) for note in result["warnings"]
        )
    return {
        "transcript.txt": plain + "\n",
        "transcript.md": markdown + "\n",
        "transcript.json": json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    }


def bundle(result):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in render(result).items():
            archive.writestr(name, data)
    return buffer.getvalue()
