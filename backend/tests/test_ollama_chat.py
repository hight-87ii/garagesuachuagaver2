"""Ollama chỉ nhận prompt đã lọc qua AIService, không cần OpenAI key."""

import json
from types import SimpleNamespace

import pytest

from backend.ai_service import AIService


def test_openai_provider_is_rejected_even_with_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unused-secret")
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert AIService().provider == "ollama"
    assert AIService(api_key="unused-secret").provider == "ollama"
    with pytest.raises(ValueError, match="chỉ hỗ trợ ollama"):
        AIService(provider="openai")


def test_legacy_api_key_never_selects_remote_client(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"message": {"content": "Phản hồi từ Ollama"}})
    monkeypatch.setattr("httpx.post", post)
    assert AIService(api_key="old-key")._chat([{"role": "user", "content": "Xin chào"}]) == "Phản hồi từ Ollama"
    assert calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert calls[0][1]["json"]["stream"] is False


def test_technical_uses_local_ollama_and_source_context(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"message": {"content": "Theo tài liệu, cần kiểm tra thực tế."}})
    monkeypatch.setattr("httpx.post", post)
    service = AIService(api_key="", provider="ollama", model="qwen2.5:7b")
    article = dict(title="Khó nổ", symptoms="Đề không lên", content="Kiểm tra tại xưởng.",
                   safety="Không cố đề máy khi ngập.", safety_level="high", source_name="Tài liệu nội bộ",
                   document_version="1", vehicle_make="", vehicle_model="", year_from=None,
                   year_to=None, engine_code="", excerpts=[{"content": "Kiểm tra ắc quy."}])

    result = service.answer_technical("Xe khó nổ", [article], "Khách hàng")

    assert result.provider == "ollama" and result.model == "qwen2.5:7b"
    assert calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert calls[0][1]["json"]["model"] == "qwen2.5:7b"
    messages = calls[0][1]["json"]["messages"]
    payload = json.loads(messages[1]["content"])
    assert payload["technical_articles"][0]["excerpts"] == ["Kiểm tra ắc quy."]
    assert "không kết luận nguyên nhân" in messages[0]["content"].lower()


def test_empty_ollama_technical_reply_falls_back_locally(monkeypatch):
    monkeypatch.setattr("httpx.post", lambda *_, **__: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"message": {"content": ""}}))
    article = dict(title="Phanh", symptoms="Kêu", content="Kiểm tra phanh.", safety="", safety_level="low",
                   source_name="Nguồn", document_version="", vehicle_make="", vehicle_model="",
                   year_from=None, year_to=None, engine_code="", excerpts=[])
    result = AIService(api_key="", provider="ollama").answer_technical("Phanh kêu", [article], "Khách hàng")
    assert result.status == "fallback" and "Kiểm tra phanh" in result.content
