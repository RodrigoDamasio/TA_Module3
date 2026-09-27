"""Evaluation harness: deterministic scoring and the real-call cap (0 real calls)."""

import pytest
from fakes import FakeLLM

from app.domain.errors import BudgetExceeded, LLMQuotaExceeded
from app.domain.ports import LLMRequest, UserMessage
from eval.run import Meter, score

FLASK = {"source_framework": "flask", "target_framework": "fastapi"}
REQ = LLMRequest("sys", [UserMessage("hi")])


def test_meter_caps_real_calls_and_remembers_why_it_stopped():
    meter = Meter(FakeLLM(), max_calls=2)
    meter.generate(REQ)
    meter.generate(REQ)
    with pytest.raises(BudgetExceeded):
        meter.generate(REQ)
    assert meter.calls == 2 and meter.stop_reason == "max-calls reached"

    quota = Meter(FakeLLM(fail={"any": LLMQuotaExceeded("day", 60)}), max_calls=5)
    with pytest.raises(LLMQuotaExceeded):
        quota.generate(REQ)
    assert quota.stop_reason == "daily quota"


def test_score_rechecks_the_final_files(harness):
    h = harness()
    job = h.run(h.new_job())
    s = score(job, FLASK)
    assert s["success"] and s["compiles"] and s["framework_migrated"]
    assert s["routes_preserved"] and s["routes_detail"] == "5/5 routes"
    assert s["undefined_names"] == 0 and s["calls"] == 5


def test_a_failed_job_scores_nothing(harness):
    broken = "from fastapi import FastAPI\napp = FastAPI()\nprint(undefined_thing)\n"
    h = harness(FakeLLM(step_files={"main.py": broken}, confidence=10))
    s = score(h.run(h.new_job()), FLASK)
    assert not s["completed"] and not s["success"] and s["files"] == 0 and not s["compiles"]
    assert "F821" in s["errors"][0]
