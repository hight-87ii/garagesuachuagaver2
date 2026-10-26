"""Ollama chỉ nhận prompt đã lọc qua AIService, không cần OpenAI key."""

import json
import sys
from types import SimpleNamespace

from backend.ai_service import AIService


def test_technical_uses_local_ollama_and_source_context(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Theo tài liệu, cần kiểm tra thực tế."))])

    def client(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=client))
    service = AIService(api_key="", provider="ollama", model="qwen2.5:7b")
    article = dict(title="Khó nổ", symptoms="Đề không lên", content="Kiểm tra tại xưởng.",
                   safety="Không cố đề máy khi ngập.", safety_level="high", source_name="Tài liệu nội bộ",
                   document_version="1", vehicle_make="", vehicle_model="", year_from=None,
                   year_to=None, engine_code="", excerpts=[{"content": "Kiểm tra ắc quy."}])

    result = service.answer_technical("Xe khó nổ", [article], "Khách hàng")

    assert result.provider == "ollama" and result.model == "qwen2.5:7b"
    assert calls[0]["base_url"] == "http://127.0.0.1:11434/v1"
    assert calls[0]["api_key"] == "ollama"
    assert calls[1]["model"] == "qwen2.5:7b"
    payload = json.loads(calls[1]["messages"][1]["content"])
    assert payload["technical_articles"][0]["excerpts"] == ["Kiểm tra ắc quy."]
    assert "không kết luận nguyên nhân" in calls[1]["messages"][0]["content"].lower()


def test_empty_ollama_technical_reply_falls_back_locally(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))]))))))
    article = dict(title="Phanh", symptoms="Kêu", content="Kiểm tra phanh.", safety="", safety_level="low",
                   source_name="Nguồn", document_version="", vehicle_make="", vehicle_model="",
                   year_from=None, year_to=None, engine_code="", excerpts=[])
    result = AIService(api_key="", provider="ollama").answer_technical("Phanh kêu", [article], "Khách hàng")
    assert result.status == "fallback" and "Kiểm tra phanh" in result.content
