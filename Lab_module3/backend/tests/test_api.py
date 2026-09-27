"""HTTP contract, SSE, approval/rollback, RFC 9457 problems, guards, samples (P1–P6).
Fake LLM, temp database, real background runner — 0 real calls."""

import json
import threading
import time

import pytest
from conftest import sample_files
from fakes import FakeLLM

from app.domain.errors import LLMQuotaExceeded

PROBLEM = "application/problem+json"
ORIGIN = "http://localhost:3000"
FLASK = {"source_framework": "flask", "target_framework": "fastapi", "require_approval": False}


def files(pair: str = "flask-fastapi") -> list[dict]:
    return [{"path": p, "content": c} for p, c in sample_files(pair).items()]


def assert_problem(r, status: int, slug: str) -> dict:
    assert r.status_code == status, r.text
    assert r.headers["content-type"] == PROBLEM
    body = r.json()
    assert body["status"] == status and body["title"]
    assert body["type"] == f"http://localhost:8000/problems/{slug}"
    return body


def sse(client, job_id: str, last_event_id: str | None = None) -> list[dict]:
    headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
    events, current = [], {}
    with client.stream("GET", f"/migrations/{job_id}/events", headers=headers) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if not line:
                if current:
                    events.append(current)
                current = {}
            elif line.startswith(("id:", "event:", "data:")):
                key, value = line.split(":", 1)
                current[key] = value.strip()
    return events


# ---- P1 -----------------------------------------------------------------------------


def test_migrate_returns_202_and_the_job_runs_in_the_background(api):
    a = api()
    r = a.client.post("/migrate", json={"files": files(), **FLASK})
    assert r.status_code == 202
    body = r.json()
    assert r.headers["location"] == body["status_url"] == f"/migrations/{body['job_id']}"
    assert body["events_url"] == f"/migrations/{body['job_id']}/events"
    view = a.wait_for(body["job_id"], "completed")
    assert view["success"] is True
    assert [f["path"] for f in view["migrated_files"]] == ["main.py"]
    assert view["migrated_files"][0]["language"] == "python"
    assert view["plan"]["steps"][0]["status"] == "completed"
    assert view["verification"]["passed"] and view["verification"]["confidence"] == 8
    assert view["meta"]["model"] == "demo" and view["meta"]["prompt_version"] == "2"
    assert view["meta"]["llm_calls"] == 5 and view["history"] is None


def test_wait_true_returns_the_finished_job(api):
    r = api().client.post("/migrate?wait=true", json={"files": files(), **FLASK})
    assert r.status_code == 200
    assert r.json()["phase"] == "completed" and r.headers["location"].startswith("/migrations/")


def test_wait_true_needs_approval_off(api):
    a = api()
    body = {"files": files(), **FLASK, "require_approval": True}
    problem = assert_problem(
        a.client.post("/migrate?wait=true", json=body), 422, "validation-error"
    )
    assert [e["pointer"] for e in problem["errors"]] == ["#/require_approval"]
    assert a.llm.requests == []


def test_wait_timeout_is_504_and_the_job_keeps_running(api):
    a = api(FakeLLM(step_delay=0.3), sync_wait_timeout_s=0)
    r = a.client.post("/migrate?wait=true", json={"files": files(), **FLASK})
    problem = assert_problem(r, 504, "wait-timeout")
    job_id = r.headers["location"].rsplit("/", 1)[1]
    assert job_id in problem["detail"]
    assert a.wait_for(job_id, "completed")["success"]


def test_include_history_lists_every_version(api):
    a = api()
    job_id = a.submit(wait="true")["job_id"]
    history = a.client.get(f"/migrations/{job_id}?include_history=true").json()["history"]
    assert [(v["path"], v["version"], v["hidden"]) for v in history] == [("main.py", 1, False)]


@pytest.mark.parametrize("pair", ["express-fastapi", "django-fastapi", "python2-python3"])
def test_every_pair_runs_through_the_api(api, pair):
    view = api().submit(pair, wait="true")
    assert view["pair"] == pair and view["phase"] == "completed", view["errors"]


# ---- P2 — SSE ------------------------------------------------------------------------


def test_sse_streams_every_event_and_ends_after_done(api):
    a = api()
    job_id = a.submit(wait="true")["job_id"]
    events = sse(a.client, job_id)
    phases = [json.loads(e["data"])["phase"] for e in events if e["event"] == "phase"]
    assert phases == ["analysis", "planning", "execution", "verification", "completed"]
    assert events[-1]["event"] == "done" and json.loads(events[-1]["data"])["success"]
    ids = [int(e["id"]) for e in events]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_sse_resumes_after_last_event_id_without_duplicates(api):
    a = api()
    job_id = a.submit(wait="true")["job_id"]
    everything = sse(a.client, job_id)
    resumed = sse(a.client, job_id, last_event_id=everything[3]["id"])
    assert resumed == everything[4:]
    assert sse(a.client, job_id, last_event_id=everything[-1]["id"]) == []  # nothing left


def test_sse_follows_a_live_job_through_approval(api):
    a = api()
    job_id = a.submit(approval=True)["job_id"]
    a.wait_for(job_id, "awaiting_approval")
    timer = threading.Timer(0.6, lambda: a.client.post(f"/migrations/{job_id}/approve"))
    timer.start()
    events = sse(a.client, job_id)
    timer.join()
    phases = [json.loads(e["data"])["phase"] for e in events if e["event"] == "phase"]
    assert phases[2:] == ["awaiting_approval", "execution", "verification", "completed"]
    assert events[-1]["event"] == "done"


def test_sse_unknown_job_is_a_problem_not_a_stream(api):
    assert_problem(api().client.get("/migrations/mig_nope/events"), 404, "job-not-found")


# ---- P3 — approval, rejection, rollback ------------------------------------------------


def test_approve_runs_the_plan(api):
    a = api()
    job_id = a.submit(approval=True)["job_id"]
    waiting = a.wait_for(job_id, "awaiting_approval")
    assert waiting["plan"] and waiting["migrated_files"] == []
    assert waiting["meta"]["approval_requested_at"]
    assert a.client.post(f"/migrations/{job_id}/approve").json()["phase"] == "execution"
    assert a.wait_for(job_id, "completed")["success"]


def test_reject_with_feedback_replans_once_then_cancels(api):
    a = api()
    job_id = a.submit(approval=True)["job_id"]
    a.wait_for(job_id, "awaiting_approval")
    r = a.client.post(f"/migrations/{job_id}/reject", json={"feedback": "Use one step only."})
    assert r.status_code == 200 and r.json()["phase"] == "planning"
    replanned = a.wait_for(job_id, "awaiting_approval")
    assert replanned["plan"]["revision"] == 2 and replanned["meta"]["replans"] == 1
    plans = [
        r for r in a.llm.requests if r.response_schema and "Plan" in r.response_schema.__name__
    ]
    assert a.llm.calls("PlanLLM") == 2 and "Use one step only." in plans[-1].messages[0].text
    r = a.client.post(f"/migrations/{job_id}/reject", json={"feedback": "Still no."})
    assert r.json()["phase"] == "cancelled"


def test_reject_without_feedback_cancels(api):
    a = api()
    job_id = a.submit(approval=True)["job_id"]
    a.wait_for(job_id, "awaiting_approval")
    assert a.client.post(f"/migrations/{job_id}/reject").json()["phase"] == "cancelled"


def test_rollback_hides_every_generated_file(api):
    a = api()
    job_id = a.submit(wait="true")["job_id"]
    view = a.client.post(f"/migrations/{job_id}/rollback").json()
    assert view["phase"] == "rolled_back" and view["migrated_files"] == []
    assert [v["hidden"] for v in view["history"]] == [True]
    assert {s["status"] for s in view["plan"]["steps"]} == {"rolled_back"}
    assert view["source_files"] == files()


def test_actions_in_the_wrong_phase_are_409(api):
    a = api()
    done = a.submit(wait="true")["job_id"]
    waiting = a.submit(approval=True)["job_id"]
    a.wait_for(waiting, "awaiting_approval")
    for action, job_id in [("approve", done), ("reject", done), ("rollback", waiting)]:
        r = a.client.post(f"/migrations/{job_id}/{action}")
        assert "Cannot go from" in assert_problem(r, 409, "invalid-transition")["detail"]
    a.client.post(f"/migrations/{done}/rollback")
    assert_problem(a.client.post(f"/migrations/{done}/rollback"), 409, "invalid-transition")


# ---- P4 — problems -------------------------------------------------------------------


def test_unknown_job_is_404(api):
    c = api().client
    for r in (c.get("/migrations/mig_nope"), c.post("/migrations/mig_nope/approve")):
        assert_problem(r, 404, "job-not-found")


def test_not_json_is_400(api):
    r = api().client.post("/migrate", content="nope", headers={"Content-Type": "application/json"})
    assert_problem(r, 400, "malformed-request")


@pytest.mark.parametrize(
    "body, pointer",
    [
        ({"files": [], **FLASK}, "#/files"),
        ({"source_framework": "flask", "target_framework": "fastapi"}, "#/files"),
        ({"files": [{"path": "app.py", "content": ""}], **FLASK}, "#/files/0/content"),
        ({"files": [{"path": "../app.py", "content": "x"}], **FLASK}, "#/files"),
        ({"files": [{"path": "/etc/app.py", "content": "x"}], **FLASK}, "#/files"),
        ({"files": [{"path": "app.js", "content": "x"}], **FLASK}, "#/files"),
        ({"files": [{"path": "a.py", "content": "x"}] * 2, **FLASK}, "#/files"),
    ],
)
def test_invalid_requests_are_validation_problems(api, body, pointer):
    a = api()
    problem = assert_problem(a.client.post("/migrate", json=body), 422, "validation-error")
    assert [e["pointer"] for e in problem["errors"]] == [pointer]
    assert a.llm.requests == []


def test_unsupported_pair_is_422(api):
    body = {"files": files(), "source_framework": "cobol", "target_framework": "fastapi"}
    problem = assert_problem(api().client.post("/migrate", json=body), 422, "unsupported-migration")
    assert "flask → fastapi" in problem["detail"]


def test_too_many_files_or_characters_is_413(api):
    a = api(max_files=1, max_total_chars=100)
    r = a.client.post("/migrate", json={"files": files(), **FLASK})
    assert "At most 1 files" in assert_problem(r, 413, "input-too-large")["detail"]
    big = [{"path": "app.py", "content": "x" * 101}]
    r = a.client.post("/migrate", json={"files": big, **FLASK})
    assert "limit is 100" in assert_problem(r, 413, "input-too-large")["detail"]


def test_daily_quota_used_up_refuses_new_jobs(api):
    a = api()

    def quota_gone() -> None:
        raise LLMQuotaExceeded("day", 7200)

    a.container.service._ensure_quota = quota_gone
    r = a.client.post("/migrate", json={"files": files(), **FLASK})
    assert "tomorrow" in assert_problem(r, 503, "llm-quota-exhausted")["detail"]
    assert r.headers["retry-after"] == "7200"


def test_full_queue_is_503_busy(api):
    a = api()
    a.container.runner.has_capacity = lambda: False
    r = a.client.post("/migrate", json={"files": files(), **FLASK})
    assert_problem(r, 503, "llm-unavailable")
    assert r.headers["retry-after"] == "60"


def test_quota_used_up_mid_job_fails_the_job_not_the_request(api):
    a = api(FakeLLM(fail={"PlanLLM": LLMQuotaExceeded("day", 3600)}))
    view = a.submit(wait="true")
    assert view["phase"] == "failed" and "quota" in view["errors"][0]


def test_unexpected_errors_are_500_problems_with_cors(api):
    a = api(raise_errors=False)

    def boom(job_id):
        raise RuntimeError("secret internals")

    a.container.service.get = boom
    r = a.client.get("/migrations/mig_x", headers={"Origin": ORIGIN})
    body = assert_problem(r, 500, "internal-error")
    assert "secret internals" not in r.text
    assert body["instance"] == "/migrations/mig_x"
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_cors_preflight_allows_last_event_id_and_exposes_headers(api):
    c = api().client
    r = c.options(
        "/migrations/mig_x/events",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "last-event-id",
        },
    )
    assert r.status_code == 200
    assert "last-event-id" in r.headers["access-control-allow-headers"].lower()
    r = c.get("/health", headers={"Origin": ORIGIN})
    assert set(r.headers["access-control-expose-headers"].split(", ")) == {
        "Retry-After",
        "Location",
    }


def test_every_problem_type_is_documented(api):
    from app.api.problems import CATALOG

    c = api().client
    for slug, problem in CATALOG.items():
        body = c.get(f"/problems/{slug}").json()
        assert body["status"] == problem.status and body["description"]
    assert c.get("/problems/nope").status_code == 404


# ---- P5 — rate limit -------------------------------------------------------------------


def test_rate_limit_counts_only_new_jobs(api):
    a = api(rate_limit_jobs_per_minute=2)
    bad = {"files": files(), "source_framework": "cobol", "target_framework": "fastapi"}
    for _ in range(3):  # rejected for free: never counted
        a.client.post("/migrate", json=bad)
    first = a.submit()["job_id"]
    a.submit()
    r = a.client.post("/migrate", json={"files": files(), **FLASK})
    assert_problem(r, 429, "rate-limited")
    assert 1 <= int(r.headers["retry-after"]) <= 60
    for _ in range(5):  # reads are never limited
        assert a.client.get(f"/migrations/{first}").status_code == 200


# ---- P6 — catalog endpoints --------------------------------------------------------------


def test_health_and_frameworks(api):
    c = api().client
    assert c.get("/health").json() == {"status": "ok", "model": "demo", "llm_mode": "fake"}
    pairs = {p["id"]: p for p in c.get("/frameworks").json()}
    assert set(pairs) == {"flask-fastapi", "express-fastapi", "django-fastapi", "python2-python3"}
    assert pairs["express-fastapi"]["source_extensions"] == [".cjs", ".js", ".mjs", ".ts"]


def test_samples_cost_no_llm_calls(api):
    a = api()
    catalog = a.client.get("/samples").json()
    assert [s["id"] for s in catalog] == [
        "flask_todo",
        "express_users",
        "django_articles",
        "py2_report",
    ]
    sample = a.client.get("/samples/express_users").json()
    assert [f["path"] for f in sample["files"]] == ["app.js", "routes/users.js"]
    assert sample["source_framework"] == "express" and "result" in sample
    assert a.client.get("/samples/nope").status_code == 404
    assert a.llm.requests == []


def test_every_sample_can_be_submitted_as_is(api):
    a = api()
    for s in a.client.get("/samples").json():
        sample = a.client.get(f"/samples/{s['id']}").json()
        body = {
            "files": sample["files"],
            "source_framework": s["source_framework"],
            "target_framework": s["target_framework"],
            "require_approval": False,
        }
        r = a.client.post("/migrate?wait=true", json=body)
        assert r.json()["success"], (s["id"], r.json()["errors"])


def test_restart_recovery_runs_at_startup(api, tmp_path):
    a = api()
    job_id = a.submit(approval=True)["job_id"]
    a.wait_for(job_id, "awaiting_approval")
    job = a.container.jobs.get(job_id)
    job.approve()  # simulate a crash right after approval: job left in 'execution'
    a.container.jobs.save(job)
    time.sleep(0.05)
    restarted = api()  # same database, new process
    view = restarted.client.get(f"/migrations/{job_id}").json()
    assert view["phase"] == "failed" and "restart" in view["errors"][0]


def test_gemini_wiring_needs_a_key_and_gates_on_the_breaker(tmp_path, monkeypatch):
    import dataclasses

    from app.api.dependencies import build_container
    from app.config import get_settings
    from app.infrastructure.caching_llm import CachingLLMClient

    s = dataclasses.replace(get_settings(), llm_mode="gemini", database_path=str(tmp_path / "g.db"))
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        build_container(dataclasses.replace(s, google_api_key=None))
    container = build_container(dataclasses.replace(s, google_api_key="k", runner_mode="inline"))
    assert isinstance(container.service.runner.__dict__["_orchestrator"].llm, CachingLLMClient)
    assert container.model == s.gemini_model
    container.service._ensure_quota()  # breaker closed: no error, no call


def test_queue_filling_after_the_check_fails_the_job_cleanly(api):
    from app.domain.errors import QueueFull

    a = api()

    def full(job_id):
        raise QueueFull()

    a.container.runner.submit = full
    r = a.client.post("/migrate", json={"files": files(), **FLASK})
    assert_problem(r, 503, "llm-unavailable")
    failed = a.container.jobs.jobs_in_phases({"failed"})
    assert len(failed) == 1 and "too busy" in failed[0].errors[0]
