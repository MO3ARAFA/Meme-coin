"""AI forensics layer: fail-safe, strict parsing, never a crash, never in the hot path."""

from types import SimpleNamespace

from copybot.ai_analyst import AIAnalyst, _extract_json, wallet_brief
from copybot.config import LLMConfig


class FakeMessages:
    def __init__(self, text=None, exc=None, stop_reason="end_turn"):
        self.text, self.exc, self.stop_reason, self.calls = text, exc, stop_reason, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)])


def analyst_with(messages: FakeMessages) -> AIAnalyst:
    a = AIAnalyst(LLMConfig(api_key="k"))
    a._client = SimpleNamespace(messages=messages)
    a.model = "claude-sonnet-5-5"
    return a


async def test_disabled_without_key():
    a = AIAnalyst(LLMConfig())
    assert await a.probe() is None and not a.available and "disabled" in a.status
    assert await a.judge_wallet({"address": "W"}) is None


async def test_judge_parses_json_wrapped_in_prose_and_clamps_score():
    msgs = FakeMessages('Here you go:\n{"verdict": "REJECT", "adversarial_risk_score": 140, "archetype": "farmer", '
                        '"red_flags": ["fast dumps"], "rationale": "baits followers"}\nThanks')
    out = await analyst_with(msgs).judge_wallet({"address": "W"})
    assert out["verdict"] == "REJECT" and out["adversarial_risk_score"] == 100
    sent = msgs.calls[0]
    assert "temperature" not in sent and sent["system"].startswith("You are an on-chain forensic analyst")


async def test_garbage_refusal_or_api_error_means_no_opinion():
    assert await analyst_with(FakeMessages("not json at all")).judge_wallet({}) is None
    assert await analyst_with(FakeMessages('{"verdict": "MAYBE"}')).judge_wallet({}) is None
    assert await analyst_with(FakeMessages('{"verdict": "APPROVE"}', stop_reason="refusal")).judge_wallet({}) is None
    assert await analyst_with(FakeMessages(exc=RuntimeError("503"))).overwatch({}) is None


async def test_overwatch_probability_is_bounded():
    out = await analyst_with(FakeMessages('{"trap_probability": 3.5, "red_flags": []}')).overwatch({"mint": "M"})
    assert out["trap_probability"] == 1.0


def test_extract_json_and_brief_contains_no_secrets():
    assert _extract_json('x {"a": {"b": 1}} y') == {"a": {"b": 1}}
    brief = wallet_brief({"address": "W", "win_rate": 0.7, "api_key": "sk-secret", "counterparties": ["X"]})
    assert "api_key" not in brief and brief["address"] == "W"
