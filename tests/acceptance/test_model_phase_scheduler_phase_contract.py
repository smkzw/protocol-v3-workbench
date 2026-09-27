"""P17/P18 -> A17/A18 phase contract for model_phase_scheduler.

Review evidence (review_probe_results.json):
- P17: phase_model_readiness("translation") warmed BOTH models
       (expected ['translation'], observed ['translation','triage']);
- P18: a bare HTTP 200 with unexamined body counted as model ready.

Contract fixed here (zero real models, everything monkeypatched; A16):
- phase-aware warm: only the phase-required role is probed; unmapped phases
  warm nothing (A17: 只读默认不chat，不自动同时唤醒全部);
- read-only default: readiness via /models listing, never a chat probe;
- a chat probe only passes on HTTP 200 AND matching model identity AND
  non-empty choices (A18: HTTP200但错误模型/空输出不能算通过).

Call-site audit (2026-09-27, rg over services/ tests/): since round21 the
main.py retry call site invokes the lifecycle orchestrator's ensure_phase
("translation") (best-effort try/except unchanged) and the competitor-triage
create/retry entries invoke ensure_phase("triage") the same way;
warm_translation_model / warm_triage_model keep their signatures for
compatibility but have no production caller left; phase_model_readiness
itself has zero production callers.
"""
from __future__ import annotations

import json

from tests.acceptance import _gate_testkit as kit


def _mod():
    return kit.load_scheduler_module()


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


def _patch_chat_body(monkeypatch, mod, body: bytes, status: int = 200) -> None:
    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(body, status),
    )


def _chat_body(model: str, choices: int = 1, content: str = "pong") -> bytes:
    return json.dumps({
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}
                    for _ in range(choices)],
    }).encode("utf-8")


# ------------------------------------------------------------------- P17/A17


def test_p17_translation_phase_warms_only_translation(monkeypatch):
    mod = _mod()
    probed: list[str] = []

    def fake_probe(base_url, model):
        probed.append(model)
        return True, ""

    monkeypatch.setattr(mod, "_chat_probe", fake_probe)
    doc = mod.phase_model_readiness("translation", warm=True)
    assert probed == [mod.OMLX_TRANSLATION_MODEL], probed
    assert set(doc["roles"]) == {"translation"}, doc
    assert doc["roles"]["translation"]["ready"] is True, doc


def test_p17_triage_phase_warms_only_triage(monkeypatch):
    mod = _mod()
    probed: list[str] = []

    def fake_probe(base_url, model):
        probed.append(model)
        return True, ""

    monkeypatch.setattr(mod, "_chat_probe", fake_probe)
    doc = mod.phase_model_readiness("triage", warm=True)
    assert probed == [mod.MTPLX_MODEL], probed
    assert set(doc["roles"]) == {"triage"}, doc


def test_p17_readonly_default_never_sends_chat(monkeypatch):
    mod = _mod()
    probed: list[str] = []

    def fake_probe(base_url, model):
        probed.append(model)
        return True, ""

    monkeypatch.setattr(mod, "_chat_probe", fake_probe)
    monkeypatch.setattr(mod, "list_resident_models",
                        lambda base_url: [mod.OMLX_TRANSLATION_MODEL, "other-model"])
    doc = mod.phase_model_readiness("translation")
    assert probed == [], probed
    assert doc["roles"]["translation"]["ready"] is True, doc

    monkeypatch.setattr(mod, "list_resident_models", lambda base_url: [])
    doc_absent = mod.phase_model_readiness("translation")
    assert probed == [], probed
    assert doc_absent["roles"]["translation"]["ready"] is False, doc_absent


def test_p17_unknown_phase_warms_nothing(monkeypatch):
    mod = _mod()
    probed: list[str] = []

    def fake_probe(base_url, model):
        probed.append(model)
        return True, ""

    monkeypatch.setattr(mod, "_chat_probe", fake_probe)
    doc = mod.phase_model_readiness("mystery-phase", warm=True)
    assert probed == [], probed
    assert doc["unknown_phase"] is True, doc
    assert doc["roles"] == {}, doc


# ------------------------------------------------------------------- P18/A18


def test_p18_probe_rejects_wrong_model_identity(monkeypatch):
    mod = _mod()
    _patch_chat_body(monkeypatch, mod, _chat_body("SOME-OTHER-MODEL"))
    ok, err = mod._chat_probe(mod.OMLX_BASE, mod.OMLX_TRANSLATION_MODEL)
    assert ok is False, (ok, err)
    assert "model_mismatch" in err, err


def test_p18_probe_rejects_empty_choices(monkeypatch):
    mod = _mod()
    _patch_chat_body(monkeypatch, mod, _chat_body(mod.OMLX_TRANSLATION_MODEL, choices=0))
    ok, err = mod._chat_probe(mod.OMLX_BASE, mod.OMLX_TRANSLATION_MODEL)
    assert ok is False, (ok, err)
    assert "empty" in err, err


def test_p18_probe_rejects_unparseable_body(monkeypatch):
    mod = _mod()
    _patch_chat_body(monkeypatch, mod, b"this is not json")
    ok, err = mod._chat_probe(mod.OMLX_BASE, mod.OMLX_TRANSLATION_MODEL)
    assert ok is False, (ok, err)
    assert "probe_body_unparseable" in err, err


def test_p18_probe_accepts_matching_nonempty_response(monkeypatch):
    mod = _mod()
    _patch_chat_body(monkeypatch, mod, _chat_body(mod.OMLX_TRANSLATION_MODEL))
    ok, err = mod._chat_probe(mod.OMLX_BASE, mod.OMLX_TRANSLATION_MODEL)
    assert ok is True, (ok, err)
    assert err == "", err


def test_p18_resident_listing_requires_model_id(monkeypatch):
    mod = _mod()
    # /models answering HTTP 200 with an unrelated catalog must not claim
    # the target model is resident (A18: 目录不冒充resident)
    _patch_chat_body(monkeypatch, mod,
                     json.dumps({"data": [{"id": "other-model"}]}).encode("utf-8"))
    listed = mod.list_resident_models(mod.OMLX_BASE)
    assert listed == ["other-model"], listed
    assert mod.OMLX_TRANSLATION_MODEL not in listed
