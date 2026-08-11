"""Unit tests for compliance.evaluator with a mocked LLM client."""
import json

import pytest

from compliance import evaluator as E


# --------------------------------------------------------------------------
# Mock OpenAI-compatible client
# --------------------------------------------------------------------------

class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, outputs):
        self._outputs = outputs
        self.calls = 0
        self.seen = []

    def create(self, model, messages, temperature):
        self.seen.append({"model": model, "temperature": temperature, "messages": messages})
        out = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return _Resp(out)


class _Chat:
    def __init__(self, outputs):
        self.completions = _Completions(outputs)


class FakeLLM:
    def __init__(self, outputs):
        self.chat = _Chat(outputs)


MESSAGES = [
    {"call_index": 1, "speaker": "SPEAKER_1", "timestamp": "00:00.00 -> 00:01.00", "text": "halo selamat siang"},
    {"call_index": 1, "speaker": "SPEAKER_0", "timestamp": "00:01.00 -> 00:02.00", "text": "iya pak"},
    {"call_index": 2, "speaker": "SPEAKER_1", "timestamp": "00:00.00 -> 00:03.00", "text": "panggilan kedua"},
]


# --------------------------------------------------------------------------
# format_transcript_for_llm
# --------------------------------------------------------------------------

def test_format_plain_markers_without_source_files():
    txt = E.format_transcript_for_llm(MESSAGES)
    assert "=== Panggilan ke-1 ===" in txt
    assert "=== Panggilan ke-2 ===" in txt
    assert "[SPEAKER_1]" in txt and "[SPEAKER_0]" in txt
    assert "halo selamat siang" in txt


def test_format_enriched_markers_with_source_files():
    src = ["201134FTJu_20260520110338.pdf", "201134FTJu_20260520111326.pdf"]
    txt = E.format_transcript_for_llm(MESSAGES, src)
    assert (
        "=== Panggilan ke-1 (ticket_id: 201134FTJu_20260520110338, id: 201134FTJu, "
        "file: 201134FTJu_20260520110338.pdf, waktu: 2026-05-20 11:03:38) ===" in txt
    )
    assert (
        "=== Panggilan ke-2 (ticket_id: 201134FTJu_20260520111326, id: 201134FTJu, "
        "file: 201134FTJu_20260520111326.pdf, waktu: 2026-05-20 11:13:26) ===" in txt
    )


# --------------------------------------------------------------------------
# evaluate — JSON parse paths
# --------------------------------------------------------------------------

def test_evaluate_direct_json():
    llm = FakeLLM(['{"ai_summary": "ok", "call_id": "x"}'])
    out = E.evaluate("PROMPT", MESSAGES, "KB", "SC", llm, "model-x")
    assert out == {"ai_summary": "ok", "call_id": "x"}
    assert llm.chat.completions.calls == 1
    assert llm.chat.completions.seen[0]["temperature"] == 0.0
    assert llm.chat.completions.seen[0]["model"] == "model-x"


def test_evaluate_code_fence():
    llm = FakeLLM(['Sini hasilnya:\n```json\n{"a": 1}\n```\n'])
    assert E.evaluate("P", MESSAGES, "KB", "SC", llm, "m") == {"a": 1}


def test_evaluate_outermost_braces_with_prose():
    llm = FakeLLM(['Tentu! {"b": [1, 2], "c": {"d": 3}} selesai'])
    assert E.evaluate("P", MESSAGES, "KB", "SC", llm, "m") == {"b": [1, 2], "c": {"d": 3}}


# --------------------------------------------------------------------------
# evaluate — retry behaviour
# --------------------------------------------------------------------------

def test_evaluate_retries_then_succeeds():
    llm = FakeLLM(["bukan json sama sekali", '{"ok": true}'])
    out = E.evaluate("P", MESSAGES, "KB", "SC", llm, "m", max_retries=2)
    assert out == {"ok": True}
    assert llm.chat.completions.calls == 2


def test_evaluate_all_fail_raises_after_max_attempts():
    llm = FakeLLM(["nope"])
    with pytest.raises(ValueError):
        E.evaluate("P", MESSAGES, "KB", "SC", llm, "m", max_retries=2)
    # max_retries=2 → 3 attempts total
    assert llm.chat.completions.calls == 3


# --------------------------------------------------------------------------
# evaluate — raw text embedding (no json.dumps wrapping)
# --------------------------------------------------------------------------

def test_evaluate_embeds_raw_kb_and_scorecard():
    llm = FakeLLM(['{"ok": 1}'])
    kb_raw = "KB-RAW-LINE\n[ bukan json"
    sc_raw = "SC-RAW{ , ]"
    E.evaluate("PROMPTX", MESSAGES, kb_raw, sc_raw, llm, "m")
    sent = llm.chat.completions.seen[0]
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][0]["content"] == "PROMPTX"
    user = sent["messages"][1]["content"]
    # raw text appears verbatim, not JSON-escaped
    assert "KB:\nKB-RAW-LINE\n[ bukan json" in user
    assert "SCORECARD:\nSC-RAW{ , ]" in user
    assert "(JSON)" not in user
