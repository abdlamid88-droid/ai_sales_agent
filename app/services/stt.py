"""
Speech-to-Text (STT) Service
============================
Transcribes incoming audio/voice notes using Groq API (whisper-large-v3) or OpenAI Whisper API (whisper-1).
Supports Algerian Darja and French automotive vocabulary prompt context.
"""

import os
import logging
from typing import Optional

try:
    from groq import Groq, AsyncGroq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

try:
    import openai
    from openai import OpenAI, AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

logger = logging.getLogger(__name__)

AUTO_PARTS_PROMPT = "تسجيل صوتي لعميل يطلب قطعة غيار سيارات بالدارجة الجزائرية والفرنسية"
GROQ_WHISPER_MODEL = "whisper-large-v3"
OPENAI_WHISPER_MODEL = "whisper-1"


def transcribe_audio_groq(file_path: str) -> str:
    """
    Transcribe an audio file using Groq API with Whisper-Large-v3 (whisper-large-v3).
    
    Args:
        file_path (str): Local path to audio file (.ogg, .m4a, .mp3, .wav, etc.)
        
    Returns:
        str: Transcribed text or empty string on failure/missing file.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning("[STT_GROQ] Audio file path missing or invalid: %s", file_path)
        return ""

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not HAS_GROQ:
        logger.warning("[STT_GROQ] GROQ_API_KEY is not configured or groq package missing.")
        return ""

    try:
        client = Groq(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=GROQ_WHISPER_MODEL,
                file=audio_file,
                prompt=AUTO_PARTS_PROMPT
            )
        text = getattr(transcript, "text", "") or ""
        logger.info("[STT_GROQ] Transcribed %s -> '%s'", file_path, text)
        return text.strip()
    except Exception as exc:
        logger.error("[STT_GROQ] Groq Whisper-Large-v3 transcription failed for %s: %s", file_path, exc)
        return ""


async def transcribe_audio_groq_async(file_path: str) -> str:
    """
    Async variant of transcribe_audio_groq using AsyncGroq.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning("[STT_GROQ_ASYNC] Audio file path missing or invalid: %s", file_path)
        return ""

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not HAS_GROQ:
        logger.warning("[STT_GROQ_ASYNC] GROQ_API_KEY is not configured or groq package missing.")
        return ""

    try:
        client = AsyncGroq(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=GROQ_WHISPER_MODEL,
                file=audio_file,
                prompt=AUTO_PARTS_PROMPT
            )
        text = getattr(transcript, "text", "") or ""
        logger.info("[STT_GROQ_ASYNC] Transcribed %s -> '%s'", file_path, text)
        return text.strip()
    except Exception as exc:
        logger.error("[STT_GROQ_ASYNC] Groq Whisper-Large-v3 transcription failed for %s: %s", file_path, exc)
        return ""


def transcribe_audio_openai(file_path: str) -> str:
    """
    Transcribe an audio file using OpenAI Whisper API (whisper-1).
    
    Args:
        file_path (str): Local path to audio file (.ogg, .m4a, .mp3, .wav, etc.)
        
    Returns:
        str: Transcribed text or empty string on failure/missing file.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning("[STT_OPENAI] Audio file path missing or invalid: %s", file_path)
        return ""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not HAS_OPENAI:
        logger.warning("[STT_OPENAI] OPENAI_API_KEY is not configured or openai package missing.")
        return ""

    try:
        client = OpenAI(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=OPENAI_WHISPER_MODEL,
                file=audio_file,
                prompt=AUTO_PARTS_PROMPT
            )
        text = getattr(transcript, "text", "") or ""
        logger.info("[STT_OPENAI] Transcribed %s -> '%s'", file_path, text)
        return text.strip()
    except Exception as exc:
        logger.error("[STT_OPENAI] OpenAI Whisper transcription failed for %s: %s", file_path, exc)
        return ""


async def transcribe_audio_openai_async(file_path: str) -> str:
    """
    Async variant of transcribe_audio_openai for non-blocking I/O.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning("[STT_OPENAI_ASYNC] Audio file path missing or invalid: %s", file_path)
        return ""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not HAS_OPENAI:
        logger.warning("[STT_OPENAI_ASYNC] OPENAI_API_KEY is not configured or openai package missing.")
        return ""

    try:
        client = AsyncOpenAI(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=OPENAI_WHISPER_MODEL,
                file=audio_file,
                prompt=AUTO_PARTS_PROMPT
            )
        text = getattr(transcript, "text", "") or ""
        logger.info("[STT_OPENAI_ASYNC] Transcribed %s -> '%s'", file_path, text)
        return text.strip()
    except Exception as exc:
        logger.error("[STT_OPENAI_ASYNC] OpenAI Whisper transcription failed for %s: %s", file_path, exc)
        return ""
