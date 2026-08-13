"""
Unit tests for Speech-to-Text (STT) Service with Groq (Whisper-Large-v3) & OpenAI Whisper API integration.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.services.stt import (
    transcribe_audio_groq,
    transcribe_audio_groq_async,
    transcribe_audio_openai,
    transcribe_audio_openai_async,
    AUTO_PARTS_PROMPT,
    GROQ_WHISPER_MODEL,
    OPENAI_WHISPER_MODEL
)
from app.services.media import download_whatsapp_audio


class TestSTTService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Create a temporary fake audio file
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fake_audio_path = os.path.join(self.temp_dir.name, "test_voice.ogg")
        with open(self.fake_audio_path, "wb") as f:
            f.write(b"OggS_fake_audio_header_and_data_content")

    def tearDown(self):
        self.temp_dir.cleanup()

    # --- Groq STT Tests ---

    def test_transcribe_audio_groq_missing_file(self):
        # Test non-existent file path
        res = transcribe_audio_groq("/tmp/non_existent_audio_file_12345.ogg")
        self.assertEqual(res, "")

    def test_transcribe_audio_groq_empty_path(self):
        # Test empty string path
        res = transcribe_audio_groq("")
        self.assertEqual(res, "")

    @patch.dict(os.environ, {}, clear=True)
    def test_transcribe_audio_groq_missing_api_key(self):
        # Test when GROQ_API_KEY is not configured
        res = transcribe_audio_groq(self.fake_audio_path)
        self.assertEqual(res, "")

    @patch("app.services.stt.Groq")
    @patch.dict(os.environ, {"GROQ_API_KEY": "gsk_fake_test_key_12345"})
    def test_transcribe_audio_groq_success(self, mock_groq_cls):
        # Mock Groq Client & Audio Transcription response
        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        
        mock_transcript = MagicMock()
        mock_transcript.text = "نحتاج انتفول طاكسي كيو كيو"
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        result = transcribe_audio_groq(self.fake_audio_path)
        
        self.assertEqual(result, "نحتاج انتفول طاكسي كيو كيو")
        mock_client.audio.transcriptions.create.assert_called_once()
        
        call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(call_kwargs.get("model"), "whisper-large-v3")
        self.assertEqual(call_kwargs.get("prompt"), AUTO_PARTS_PROMPT)

    @patch("app.services.stt.AsyncGroq")
    @patch.dict(os.environ, {"GROQ_API_KEY": "gsk_fake_test_key_12345"})
    async def test_transcribe_audio_groq_async_success(self, mock_async_groq_cls):
        # Mock AsyncGroq Client
        mock_client = MagicMock()
        mock_async_groq_cls.return_value = mock_client
        
        mock_transcript = MagicMock()
        mock_transcript.text = "خصني امورتيسورات جولف 7"
        
        async def mock_create(**kwargs):
            return mock_transcript

        mock_client.audio.transcriptions.create = mock_create

        result = await transcribe_audio_groq_async(self.fake_audio_path)
        self.assertEqual(result, "خصني امورتيسورات جولف 7")

    # --- OpenAI STT Tests ---

    def test_transcribe_audio_openai_missing_file(self):
        res = transcribe_audio_openai("/tmp/non_existent_audio_file_12345.ogg")
        self.assertEqual(res, "")

    def test_transcribe_audio_openai_empty_path(self):
        res = transcribe_audio_openai("")
        self.assertEqual(res, "")

    @patch.dict(os.environ, {}, clear=True)
    def test_transcribe_audio_openai_missing_api_key(self):
        res = transcribe_audio_openai(self.fake_audio_path)
        self.assertEqual(res, "")

    @patch("app.services.stt.OpenAI")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-test-key"})
    def test_transcribe_audio_openai_success(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        
        mock_transcript = MagicMock()
        mock_transcript.text = "خصني امورتيسورات شيري كيو كيو"
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        result = transcribe_audio_openai(self.fake_audio_path)
        
        self.assertEqual(result, "خصني امورتيسورات شيري كيو كيو")
        mock_client.audio.transcriptions.create.assert_called_once()
        
        call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(call_kwargs.get("model"), "whisper-1")
        self.assertEqual(call_kwargs.get("prompt"), AUTO_PARTS_PROMPT)

    @patch("app.services.stt.AsyncOpenAI")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-test-key"})
    async def test_transcribe_audio_openai_async_success(self, mock_async_openai_cls):
        mock_client = MagicMock()
        mock_async_openai_cls.return_value = mock_client
        
        mock_transcript = MagicMock()
        mock_transcript.text = "خصني ديسك دو فران"
        
        async def mock_create(**kwargs):
            return mock_transcript

        mock_client.audio.transcriptions.create = mock_create

        result = await transcribe_audio_openai_async(self.fake_audio_path)
        self.assertEqual(result, "خصني ديسك دو فران")

    @patch("app.services.media.fetch_whatsapp_media_bytes")
    async def test_download_whatsapp_audio(self, mock_fetch_bytes):
        mock_fetch_bytes.return_value = (b"fake_audio_bytes_content", "audio/ogg; codecs=opus")

        media_id = "test_media_id_999"
        file_path = await download_whatsapp_audio(media_id)

        self.assertIsNotNone(file_path)
        self.assertTrue(os.path.exists(file_path))
        self.assertTrue("media/audio/test_media_id_999.ogg" in file_path)

        with open(file_path, "rb") as f:
            content = f.read()
        self.assertEqual(content, b"fake_audio_bytes_content")

        if os.path.exists(file_path):
            os.remove(file_path)


if __name__ == "__main__":
    unittest.main()
