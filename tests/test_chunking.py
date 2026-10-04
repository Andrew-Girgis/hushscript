import numpy as np
import pytest

from hushscript.native import RATE, assign_speakers, keep_word, windows


@pytest.mark.parametrize("seconds", [0.1, 40, 40.1, 600, 1200])
def test_windows_cover_recording_once_with_bounded_context(seconds):
    count = int(seconds * RATE)
    chunks = list(windows(count))
    assert chunks[0][0] == 0
    assert chunks[-1][1] == count
    assert chunks[0][2] == 0
    assert chunks[-1][3] == seconds
    for begin, finish, left, right in chunks:
        assert 0 <= begin < finish <= count
        assert finish - begin <= 44 * RATE
        assert begin / RATE <= left < right <= finish / RATE
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert previous[3] == following[2]


def test_overlap_word_emitted_once_and_offset_applied():
    args = {"offset": 38, "left": 40, "right": 80, "duration": 100}
    assert keep_word("before", 1, 1.5, **args) is None
    word = keep_word("boundary", 1.9, 2.1, **args)
    assert word["start"] == 39.9 and word["end"] == 40.1
    assert keep_word("later", 41.9, 42.1, **args) is None


def test_speaker_identity_persists_and_uncertainty_stays_unlabelled():
    words = [{"start": i, "end": i + 0.8, "speaker": None} for i in range(4)]
    probabilities = np.array([[0.1, 0.9], [0.9, 0.1], [0.1, 0.9], [0.05, 0.05]])
    assign_speakers(words, probabilities, 1)
    assert [word["speaker"] for word in words] == ["speaker_1", "speaker_2", "speaker_1", None]
