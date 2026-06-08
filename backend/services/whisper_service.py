from __future__ import annotations

from pathlib import Path
import shutil
from typing import Union

from openai import OpenAI

from config import get_settings


SUPPORTED_EXTENSIONS = {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"}


def transcribe(audio_path: Union[str, Path]) -> str:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    prepared_path = _prepare_audio_path(Path(audio_path))
    with prepared_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(
            model=settings.openai_transcription_model,
            file=audio_file,
        )
    return result.text


def _prepare_audio_path(audio_path: Path) -> Path:
    if not audio_path.exists():
        return audio_path

    detected_extension = _detect_audio_extension(audio_path)
    current_extension = audio_path.suffix.lower()
    if detected_extension and detected_extension != current_extension:
        corrected_path = audio_path.with_suffix(detected_extension)
        shutil.copy2(audio_path, corrected_path)
        return corrected_path

    if current_extension not in SUPPORTED_EXTENSIONS:
        corrected_path = audio_path.with_suffix(detected_extension or ".wav")
        shutil.copy2(audio_path, corrected_path)
        return corrected_path

    return audio_path


def _detect_audio_extension(audio_path: Path) -> str | None:
    header = audio_path.read_bytes()[:64]
    if header.startswith(b"RIFF") and b"WAVE" in header[:16]:
        return ".wav"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if header.startswith(b"OggS"):
        return ".ogg"
    if header.startswith(b"fLaC"):
        return ".flac"
    if header.startswith(b"ID3") or _looks_like_mp3_frame(header):
        return ".mp3"
    if len(header) > 12 and header[4:8] == b"ftyp":
        brand_block = header[8:32]
        if b"M4A" in brand_block or b"m4a" in brand_block:
            return ".m4a"
        return ".mp4"
    return None


def _looks_like_mp3_frame(header: bytes) -> bool:
    return len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
