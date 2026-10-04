"""Pinned NeMo-Speech.cpp C ABI, with bounded ASR windows and recording-wide diarization."""

import ctypes as c
from pathlib import Path

import numpy as np

SIZE = c.c_size_t
PTR = c.c_void_p
I32 = c.c_int32
RATE = 16000


class Backend(c.Structure):
    _fields_ = [("size", SIZE), ("gpu", I32)]


class Model(c.Structure):
    _fields_ = [("size", SIZE), ("path", c.c_char_p), ("name", c.c_char_p)]


class Config(c.Structure):
    _fields_ = [("size", SIZE)] + [
        (x, PTR)
        for x in (
            "backend",
            "model",
            "streaming",
            "decoder",
            "vad",
            "endpointing",
            "postproc",
            "diar",
            "batching",
        )
    ]


class Batching(c.Structure):
    _fields_ = [
        ("size", SIZE),
        ("enable", c.c_bool),
        ("max_batch_size", I32),
        ("max_queue_delay_us", I32),
        ("max_queue_depth", I32),
        ("ingress_cohort_delay_us", I32),
        ("state_arena_slots", I32),
    ]


class Options(c.Structure):
    _fields_ = [
        ("size", SIZE),
        ("request_id", c.c_char_p),
        ("language_code", c.c_char_p),
        ("interim_results", c.c_bool),
        ("enable_word_time_offsets", c.c_bool),
        ("enable_automatic_punctuation", c.c_bool),
        ("verbatim_transcripts", c.c_bool),
        ("profanity_filter", c.c_bool),
        ("stop_history_eou_ms", I32),
        ("speech_contexts", PTR),
        ("speech_context_count", SIZE),
        ("max_alternatives", I32),
        ("enable_speaker_diarization", c.c_bool),
        ("max_speaker_count", I32),
    ]


class DiarModel(c.Structure):
    _fields_ = [
        ("size", SIZE),
        ("model_path", c.c_char_p),
        ("gpu", I32),
        ("preset", c.c_char_p),
        ("chunk_frames", I32),
        ("right_context_frames", I32),
        ("left_context_frames", I32),
        ("fifo_frames", I32),
        ("spkcache_frames", I32),
        ("update_period_frames", I32),
    ]


def pointer(value):
    return c.cast(c.pointer(value), PTR)


def bind(lib, name, args, result):
    function = getattr(lib, "nemo_speech_" + name)
    function.argtypes, function.restype = args, result
    return function


def windows(sample_count, core_seconds=40, context_seconds=2):
    """Return bounded sample views and disjoint ownership intervals in seconds."""
    core = core_seconds * RATE
    context = context_seconds * RATE
    for left in range(0, sample_count, core):
        right = min(left + core, sample_count)
        yield max(0, left - context), min(sample_count, right + context), left / RATE, right / RATE


def keep_word(text, start, end, *, offset, left, right, duration):
    start, end = start + offset, end + offset
    middle = (start + end) / 2
    if not left <= middle < right:
        return None
    return {
        "text": text,
        "start": round(max(0, min(start, duration)), 3),
        "end": round(max(0, min(max(start, end), duration)), 3),
        "speaker": None,
    }


def recognize(lib, samples, model_dir, gpu):
    create = bind(lib, "asr_create", [c.POINTER(Config), c.POINTER(PTR)], I32)
    destroy = bind(lib, "asr_destroy", [PTR], None)
    default = bind(lib, "asr_recognition_options_default", [], Options)
    infer = bind(
        lib,
        "asr_recognize_f32",
        [PTR, c.POINTER(Options), c.POINTER(c.c_float), SIZE, I32, c.POINTER(PTR)],
        I32,
    )
    free_result = bind(lib, "asr_result_destroy", [PTR], None)
    count = bind(lib, "asr_result_word_count", [PTR, SIZE], SIZE)
    getters = {
        key: bind(lib, "asr_result_word_" + key, [PTR, SIZE, SIZE], kind)
        for key, kind in (("text", c.c_char_p), ("start_time", I32), ("end_time", I32))
    }
    backend = Backend(c.sizeof(Backend), gpu)
    model = Model(
        c.sizeof(Model), str(Path(model_dir) / "parakeet-tdt-0.6b-v3.q8_0.gguf").encode(), None
    )
    batching = Batching(c.sizeof(Batching), False, 1, 0, 1, 0, 1)
    config = Config()
    config.size = c.sizeof(Config)
    config.backend, config.model, config.batching = (
        pointer(backend),
        pointer(model),
        pointer(batching),
    )
    handle = PTR()
    words = []
    duration = len(samples) / RATE
    try:
        if create(c.byref(config), c.byref(handle)):
            raise RuntimeError(
                "The transcription model could not load. Check memory and GPU setup."
            )
        opts = default()
        opts.language_code = b"en-US"
        opts.enable_word_time_offsets = True
        opts.enable_speaker_diarization = False
        opts.enable_automatic_punctuation = True
        opts.profanity_filter = False
        for begin, finish, left, right in windows(len(samples)):
            chunk = samples[begin:finish]
            if float(np.max(np.abs(chunk))) < 0.0001:
                continue
            result = PTR()
            try:
                if infer(
                    handle,
                    c.byref(opts),
                    chunk.ctypes.data_as(c.POINTER(c.c_float)),
                    len(chunk),
                    RATE,
                    c.byref(result),
                ):
                    raise RuntimeError("Local transcription failed. Check available memory.")
                for i in range(count(result, 0)):
                    word = keep_word(
                        (getters["text"](result, 0, i) or b"").decode("utf-8"),
                        getters["start_time"](result, 0, i) / 1000,
                        getters["end_time"](result, 0, i) / 1000,
                        offset=begin / RATE,
                        left=left,
                        right=right,
                        duration=duration,
                    )
                    if word:
                        words.append(word)
            finally:
                if result:
                    free_result(result)
    finally:
        if handle:
            destroy(handle)
    return words


def assign_speakers(words, probabilities, seconds_per_frame):
    labels = {}
    for word in words:
        begin = max(0, int(word["start"] / seconds_per_frame))
        end = min(len(probabilities), max(begin + 1, int(np.ceil(word["end"] / seconds_per_frame))))
        if begin >= end:
            continue
        scores = probabilities[begin:end].mean(axis=0)
        tag = int(np.argmax(scores))
        if float(scores[tag]) < 0.2:
            continue
        if tag not in labels:
            labels[tag] = f"speaker_{len(labels) + 1}"
        word["speaker"] = labels[tag]


def diarize_words(lib, samples, words, model_dir, gpu):
    create = bind(lib, "diar_create", [c.POINTER(DiarModel), c.POINTER(PTR)], I32)
    destroy = bind(lib, "diar_destroy", [PTR], None)
    open_stream = bind(lib, "diar_stream_open", [PTR, c.POINTER(PTR)], I32)
    push = bind(lib, "diar_stream_push_f32", [PTR, c.POINTER(c.c_float), SIZE, I32], I32)
    finish = bind(lib, "diar_stream_finish", [PTR], I32)
    close = bind(lib, "diar_stream_close", [PTR], None)
    count = bind(lib, "diar_frame_count", [PTR], c.c_int64)
    start = bind(lib, "diar_frame_probs_start", [PTR], c.c_int64)
    speakers = bind(lib, "diar_num_speakers", [PTR], I32)
    cadence = bind(lib, "diar_seconds_per_frame", [PTR], c.c_double)
    probs = bind(lib, "diar_frame_probs", [PTR, c.POINTER(c.c_float), SIZE], I32)
    config = DiarModel(
        c.sizeof(DiarModel),
        str(Path(model_dir) / "Nemotron-3-Diarization.q8_0.gguf").encode(),
        gpu,
        b"v3-offline",
        0,
        0,
        -1,
        0,
        0,
        0,
    )
    model, stream = PTR(), PTR()
    probabilities = None
    try:
        if create(c.byref(config), c.byref(model)) or open_stream(model, c.byref(stream)):
            raise RuntimeError("The speaker model could not load. Check memory and setup.")
        # A single continuous stream preserves speaker identities across ASR windows.
        for offset in range(0, len(samples), RATE * 10):
            chunk = samples[offset : offset + RATE * 10]
            if push(stream, chunk.ctypes.data_as(c.POINTER(c.c_float)), len(chunk), RATE):
                raise RuntimeError("Local speaker analysis failed.")
        if finish(stream) or start(stream) != 0:
            raise RuntimeError("Speaker analysis exceeded the supported recording length.")
        frame_count, speaker_count = count(stream), speakers(model)
        if frame_count <= 0 or frame_count > 121000 or not 1 <= speaker_count <= 8:
            raise RuntimeError("Speaker analysis returned an invalid timeline.")
        probabilities = np.empty((frame_count, speaker_count), dtype=np.float32)
        if probs(stream, probabilities.ctypes.data_as(c.POINTER(c.c_float)), probabilities.size):
            raise RuntimeError("Could not read the speaker timeline.")
        seconds_per_frame = cadence(model)
        if seconds_per_frame <= 0 or not np.isfinite(probabilities).all():
            raise RuntimeError("Speaker analysis returned invalid probabilities.")
        assign_speakers(words, probabilities, seconds_per_frame)
    finally:
        if probabilities is not None:
            probabilities.fill(0)
        if stream:
            close(stream)
        if model:
            destroy(model)


def transcribe(samples, *, runtime_dir, model_dir, device, diarize):
    lib = c.CDLL(str(Path(runtime_dir) / "lib/libnemo_speech_asr_c.so.1"))
    gpu = -1 if device == "cpu" else 0
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    words = recognize(lib, samples, model_dir, gpu)
    # ASR is destroyed before loading the diarizer, reducing peak VRAM.
    if diarize and words:
        diarize_words(lib, samples, words, model_dir, gpu)
    return " ".join(word["text"] for word in words).strip(), words
