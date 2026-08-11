"""
Speech-to-Text (STT) Service
============================
Transcribes incoming audio/voice notes using OpenAI Whisper API (whisper-1).
Supports Algerian Darja and French automotive vocabulary prompt context.
"""

import os
import logging
from typing import Optional

try:
    import openai
    from openai import OpenAI, AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

logger = logging.getLogger(__name__)

AUTO_PARTS_PROMPT = "تسجيل صوتي لعميل يطلب قطعة غيار سيارات بالدارجة الجزائرية والفرنسية"


def transcribe_audio_openai(file_path: str) -> str:
    """
    Transcribe an audio file using OpenAI Whisper API (whisper-1).
    
    Args:
        file_path (str): Local path to audio file (.ogg, .m4a, .mp3, .wav, etc.)
        
    Returns:
        str: Transcribed text or empty string on failure/missing file.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning("[STT] Audio file path missing or invalid: %s", file_path)
        return ""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not HAS_OPENAI:
        logger.warning("[STT] OPENAI_API_KEY is not configured or openai package missing.")
        return ""

    try:
        client = OpenAI(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                prompt=AUTO_PARTS_PROMPT
            )
        text = getattr(transcript, "text", "") or ""
        logger.info("[STT] Transcribed %s -> '%s'", file_path, text)
        return text.strip()
    except Exception as exc:
        logger.error("[STT] OpenAI Whisper transcription failed for %s: %s", file_path, exc)
        return ""


async def transcribe_audio_openai_async(file_path: str) -> str:
    """
    Async variant of transcribe_audio_openai for non-blocking I/O.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning("[STT] Audio file path missing or invalid: %s", file_path)
        return ""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not HAS_OPENAI:
        logger.warning("[STT] OPENAI_API_KEY is not configured or openai package missing.")
        return ""

    try:
        client = AsyncOpenAI(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                prompt=AUTO_PARTS_PROMPT
            )
        text = getattr(transcript, "text", "") or ""
        logger.info("[STT_ASYNC] Transcribed %s -> '%s'", file_path, text)
        return text.strip()
    except Exception as exc:
        logger.error("[STT_ASYNC] OpenAI Whisper transcription failed for %s: %s", file_path, exc)
        return ""
