"""Text-to-speech for the guide bot: Meta MMS-TTS, optional and content-addressed.

`SKETCHSCAPE_GUIDE_TTS=none` (the default, and always in tests) skips
synthesis entirely -- no `transformers`/`torch` import happens, so the base
install and the test suite stay light. `SKETCHSCAPE_GUIDE_TTS=mms` lazily
loads `facebook/mms-tts-eng` once per process, behind a lock, and writes
16-bit PCM WAV through the existing artifact store (so local and S3 both
work), keyed by `sha256(voice + text)` so the same line is never
resynthesized within a project.

License: MMS-TTS is CC-BY-NC 4.0 (already accepted for the demo in step 6).
Flag it before any commercial use.
"""

from __future__ import annotations

import hashlib
import io
import os
import struct
import threading

_model = None
_tokenizer = None
_load_lock = threading.Lock()
_SAMPLE_RATE = 16000

# ponytail: an in-process cache of digest -> duration_s. A cache *hit* on the
# artifact store (file already written by an earlier request) still needs a
# duration, and re-decoding a stored WAV isn't exposed by ArtifactStore --
# so a restart loses the duration for lines it didn't itself synthesize, and
# those get resynthesized once. A durable sidecar (store duration in a tiny
# json object next to the WAV) is the upgrade if that ever matters at scale.
_duration_cache: dict[str, float] = {}


def _tts_backend() -> str:
    return os.environ.get("SKETCHSCAPE_GUIDE_TTS", "none").strip().lower()


def _load_model():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    with _load_lock:
        if _model is None:
            from transformers import AutoTokenizer, VitsModel  # noqa: PLC0415

            _model = VitsModel.from_pretrained("facebook/mms-tts-eng")
            _tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-eng")
        return _model, _tokenizer


def _synthesize_wav(text: str) -> tuple[bytes, float]:
    import torch  # noqa: PLC0415

    model, tokenizer = _load_model()
    with torch.no_grad():
        waveform = model(**tokenizer(text, return_tensors="pt")).waveform[0].numpy()
    duration_s = len(waveform) / _SAMPLE_RATE

    import wave  # noqa: PLC0415

    pcm = b"".join(struct.pack("<h", max(-32768, min(32767, int(sample * 32767)))) for sample in waveform)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(_SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return buffer.getvalue(), duration_s


async def synthesize(project_id: str, text: str, voice: str) -> tuple[str, float]:
    """Return `(audio_url, duration_s)`. `audio_url` is `""` when TTS is
    disabled (`SKETCHSCAPE_GUIDE_TTS=none`) -- Unity then plays a chime cue
    and moves on."""
    if _tts_backend() != "mms":
        return "", 0.0

    digest = hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()
    job_id = f"guide-audio-{project_id}"
    filename = f"{digest}.wav"

    from main import artifact_store  # noqa: PLC0415 - avoids a module cycle at import time

    if digest in _duration_cache:
        return artifact_store.artifact_url(job_id, filename), _duration_cache[digest]

    wav_bytes, duration_s = _synthesize_wav(text)
    _duration_cache[digest] = duration_s

    if not artifact_store.exists(job_id, filename):
        await _write_bytes(artifact_store, job_id, filename, wav_bytes)
    return artifact_store.artifact_url(job_id, filename), duration_s


async def _write_bytes(artifact_store, job_id: str, filename: str, data: bytes) -> None:
    """`ArtifactStore.put`/`put_upload` both expect a FastAPI `UploadFile`;
    wrap the in-memory WAV bytes so the same write path (and S3 backend) is
    reused rather than reaching past the abstraction to the filesystem."""
    from fastapi import UploadFile  # noqa: PLC0415

    upload = UploadFile(filename=filename, file=io.BytesIO(data))
    await artifact_store.put(job_id, filename, upload, size_limit=len(data) + 1)
