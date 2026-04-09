"""
tests/test_bhashini_tts.py

Unit tests for core/bhashini_tts.py covering:
  - is_configured: True when both env vars present, False otherwise
  - _discover_pipeline: HTTP mocked — parses callback_url and service_id
  - _discover_pipeline: caching — second call does NOT make another HTTP request
  - _discover_pipeline: raises BhashiniUnavailableError when credentials absent
  - _discover_pipeline: raises BhashiniUnavailableError on HTTP error
  - _discover_pipeline: raises BhashiniUnavailableError on unexpected response schema
  - synthesize: returns bytes from base64-decoded audio
  - synthesize: raises BhashiniUnavailableError on inference HTTP error
  - synthesize_and_play: calls synthesize; falls back gracefully when playback unavailable
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import base64
import json
import time
import io
from unittest.mock import MagicMock, patch, call
import pytest

from core.bhashini_tts import BhashiniTTSClient, BhashiniUnavailableError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_discovery_response(lang: str = "ta", callback_url: str = "https://bhashini.example/tts",
                              service_id: str = "svc-ta-001") -> bytes:
    """Build a minimal valid Bhashini pipeline discovery response JSON."""
    body = {
        "pipelineResponseConfig": [
            {
                "config": [
                    {
                        "serviceLocation": callback_url,
                        "serviceId": service_id,
                        "sourceLanguage": lang,
                    }
                ]
            }
        ]
    }
    return json.dumps(body).encode("utf-8")


def _mock_inference_response(audio_b64: str) -> bytes:
    body = {
        "pipelineResponse": [
            {"audio": [{"audioContent": audio_b64}]}
        ]
    }
    return json.dumps(body).encode("utf-8")


def _fake_audio_bytes() -> bytes:
    """Minimal PCM WAV header (44 bytes) + silence."""
    return b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 32


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured:

    def test_both_env_vars_set(self, monkeypatch):
        monkeypatch.setenv("BHASHINI_USER_ID", "user123")
        monkeypatch.setenv("BHASHINI_API_KEY", "key456")
        client = BhashiniTTSClient()
        assert client.is_configured()

    def test_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
        monkeypatch.delenv("BHASHINI_API_KEY", raising=False)
        client = BhashiniTTSClient()
        assert not client.is_configured()

    def test_only_user_id(self, monkeypatch):
        monkeypatch.setenv("BHASHINI_USER_ID", "user123")
        monkeypatch.delenv("BHASHINI_API_KEY", raising=False)
        client = BhashiniTTSClient()
        assert not client.is_configured()

    def test_only_api_key(self, monkeypatch):
        monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
        monkeypatch.setenv("BHASHINI_API_KEY", "key456")
        client = BhashiniTTSClient()
        assert not client.is_configured()

    def test_explicit_constructor_args(self):
        client = BhashiniTTSClient(user_id="u", api_key="k")
        assert client.is_configured()

    def test_empty_strings_not_configured(self):
        client = BhashiniTTSClient(user_id="", api_key="")
        assert not client.is_configured()


# ---------------------------------------------------------------------------
# _discover_pipeline — success path
# ---------------------------------------------------------------------------

def _make_mock_urlopen(response_body: bytes, status: int = 200):
    """Return a context-manager mock that yields a fake HTTP response."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = response_body
    mock_cm = MagicMock()
    mock_cm.__enter__ = lambda s: mock_resp
    mock_cm.__exit__ = MagicMock(return_value=False)
    return mock_cm


class TestDiscoverPipeline:

    def _client(self):
        return BhashiniTTSClient(user_id="user123", api_key="key456")

    def test_returns_callback_url(self):
        client = self._client()
        disc_resp = _mock_discovery_response(callback_url="https://cb.example/tts")
        mock_cm = _make_mock_urlopen(disc_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            url, sid = client._discover_pipeline("ta")
        assert url == "https://cb.example/tts"

    def test_returns_service_id(self):
        client = self._client()
        disc_resp = _mock_discovery_response(service_id="my-service")
        mock_cm = _make_mock_urlopen(disc_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            url, sid = client._discover_pipeline("ta")
        assert sid == "my-service"

    def test_caches_result(self):
        client = self._client()
        disc_resp = _mock_discovery_response()
        mock_cm = _make_mock_urlopen(disc_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm) as mock_uo:
            client._discover_pipeline("ta")
            client._discover_pipeline("ta")
        # urlopen should have been called exactly once (cache hit on second call)
        assert mock_uo.call_count == 1

    def test_different_lang_separate_cache_entry(self):
        client = self._client()
        disc_resp = _mock_discovery_response()
        mock_cm = _make_mock_urlopen(disc_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm) as mock_uo:
            client._discover_pipeline("ta")
            client._discover_pipeline("en")
        assert mock_uo.call_count == 2

    def test_cache_expires_and_refetches(self):
        client = self._client()
        disc_resp = _mock_discovery_response()
        mock_cm = _make_mock_urlopen(disc_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm) as mock_uo:
            client._discover_pipeline("ta")
            # Manually expire cache
            with client._cache_lock:
                url, sid, _ = client._cache["ta"]
                client._cache["ta"] = (url, sid, time.monotonic() - 1)  # expired
            client._discover_pipeline("ta")
        assert mock_uo.call_count == 2

    def test_raises_when_no_credentials(self, monkeypatch):
        monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
        monkeypatch.delenv("BHASHINI_API_KEY", raising=False)
        client = BhashiniTTSClient()
        with pytest.raises(BhashiniUnavailableError, match="credentials"):
            client._discover_pipeline("ta")

    def test_raises_on_http_error(self):
        client = self._client()
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            with pytest.raises(BhashiniUnavailableError, match="discovery failed"):
                client._discover_pipeline("ta")

    def test_raises_on_bad_response_structure(self):
        client = self._client()
        bad_resp = json.dumps({"unexpected": "format"}).encode()
        mock_cm = _make_mock_urlopen(bad_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            with pytest.raises(BhashiniUnavailableError, match="Unexpected"):
                client._discover_pipeline("ta")


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------

class TestSynthesize:

    def _client(self):
        return BhashiniTTSClient(user_id="user123", api_key="key456")

    def _patch_discover(self, client, callback_url="https://cb.example/tts", sid="svc"):
        """Inject cache directly to skip discovery HTTP call."""
        with client._cache_lock:
            client._cache["ta"] = (callback_url, sid, time.monotonic() + 3600)

    def test_returns_bytes(self):
        client = self._client()
        self._patch_discover(client)
        audio = _fake_audio_bytes()
        b64 = base64.b64encode(audio).decode()
        infer_resp = _mock_discovery_response()
        mock_cm = _make_mock_urlopen(_mock_inference_response(b64))
        with patch("urllib.request.urlopen", return_value=mock_cm):
            result = client.synthesize("test", lang="ta")
        assert isinstance(result, bytes)
        assert result == audio

    def test_raises_on_inference_error(self):
        client = self._client()
        self._patch_discover(client)
        with patch("urllib.request.urlopen", side_effect=OSError("network error")):
            with pytest.raises(BhashiniUnavailableError, match="inference failed"):
                client.synthesize("test", lang="ta")

    def test_raises_on_bad_inference_structure(self):
        client = self._client()
        self._patch_discover(client)
        bad_resp = json.dumps({"pipelineResponse": []}).encode()
        mock_cm = _make_mock_urlopen(bad_resp)
        with patch("urllib.request.urlopen", return_value=mock_cm):
            with pytest.raises(BhashiniUnavailableError, match="Unexpected"):
                client.synthesize("test", lang="ta")

    def test_synthesize_uses_correct_lang(self):
        client = self._client()
        # English cache entry
        with client._cache_lock:
            client._cache["en"] = ("https://cb.example/tts", "svc-en", time.monotonic() + 3600)
        audio = _fake_audio_bytes()
        b64 = base64.b64encode(audio).decode()
        mock_cm = _make_mock_urlopen(_mock_inference_response(b64))
        with patch("urllib.request.urlopen", return_value=mock_cm) as mock_uo:
            result = client.synthesize("hello", lang="en")
        # Verify the payload contains sourceLanguage: en
        call_args = mock_uo.call_args[0][0]  # urllib.request.Request object
        sent_body = json.loads(call_args.data.decode())
        src_lang = sent_body["pipelineTasks"][0]["config"]["language"]["sourceLanguage"]
        assert src_lang == "en"

    def test_empty_text_still_returns_bytes(self):
        client = self._client()
        self._patch_discover(client)
        audio = _fake_audio_bytes()
        b64 = base64.b64encode(audio).decode()
        mock_cm = _make_mock_urlopen(_mock_inference_response(b64))
        with patch("urllib.request.urlopen", return_value=mock_cm):
            result = client.synthesize("", lang="ta")
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# synthesize_and_play
# ---------------------------------------------------------------------------

class TestSynthesizeAndPlay:

    def _client(self):
        return BhashiniTTSClient(user_id="user123", api_key="key456")

    def _patch_discover(self, client):
        with client._cache_lock:
            client._cache["ta"] = ("https://cb.example/tts", "svc", time.monotonic() + 3600)

    def test_returns_false_gracefully_when_no_audio_driver(self):
        """
        When pyaudio and aplay/afplay are all unavailable,
        synthesize_and_play must return False without raising.
        """
        client = self._client()
        self._patch_discover(client)
        audio = _fake_audio_bytes()
        b64 = base64.b64encode(audio).decode()
        mock_cm = _make_mock_urlopen(_mock_inference_response(b64))
        with patch("urllib.request.urlopen", return_value=mock_cm):
            # Patch subprocess.run to raise FileNotFoundError (aplay/afplay absent)
            with patch("subprocess.run", side_effect=FileNotFoundError):
                result = client.synthesize_and_play("test", lang="ta")
        assert result is False

    def test_raises_bhashini_error_when_synthesis_fails(self):
        """synthesize_and_play must propagate BhashiniUnavailableError."""
        client = self._client()
        self._patch_discover(client)
        with patch("urllib.request.urlopen", side_effect=OSError("err")):
            with pytest.raises(BhashiniUnavailableError):
                client.synthesize_and_play("test", lang="ta")
