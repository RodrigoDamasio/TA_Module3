"""Full job lifecycle with a fake LLM — 0 real calls (O1–O10, D6)."""

import pytest
from conftest import reference_files
from fakes import FakeLLM

from app.domain.errors import LLMQuotaExceeded
from app.domain.job import Phase
from app.domain.plan import StepStatus

PARALLEL_PLAN = [
    {
        "id": 1,
        "title": "Create models",
        "description": "Create models.py for todos.",
        "depends_on": [],
        "complexity": "low",
        "source_files": ["models.py"],
        "target_files": ["models.py"],
    },
    {
        "id": 2,
        "title": "Create schemas",
        "description": "Create schemas.py for bodies.",
        "depends_on": [],
        "complexity": "low",
        "source_files": ["app.py"],
        "target_files": ["schemas.py"],
    },
    {
        "id": 3,
        "title": "Create app",
        "description": "Create main.py with all routes.",
        "depends_on": [1, 2],
        "complexity": "medium",
        "source_files": ["app.py"],
        "target_files": ["main.py"],
    },
]
REF = reference_files("flask-fastapi")
PARALLEL_FILES = {
    "models.py": REF["models.py"],
    "schemas.py": "SCHEMA_VERSION = 1\n",
    "main.py": REF["main.py"],
}


# O1
@pytest.mark.parametrize(
    "pair", ["flask-fastapi", "express-fastapi", "django-fastapi", "python2-python3"]
)
def test_happy_path_every_pair(harness, pair):
    h = harness()
    job = h.run(h.new_job(pair))
    assert job.phase is Phase.COMPLETED, job.errors
    assert job.success and job.verification.checks_passed
    assert h.jobs.phases(job.id) == [
        "analysis",
        "planning",
        "execution",
        "verification",
        "completed",
    ]
    assert h.jobs.event_types(job.id)[-1] == "done"
    assert job.current_files()
    assert h.episodes.recent(pair, 1)[0].outcome == "success"


def test_real_reference_output_passes_checks(harness):
    h = harness(FakeLLM(plan=PARALLEL_PLAN, step_files=PARALLEL_FILES))
    job = h.run(h.new_job())
    assert job.success
    routes = next(c for c in job.verification.checks if c.name == "routes_preserved")
    assert routes.detail == "5/5 routes"


# O2
def test_approval_pauses_then_completes(harness):
    h = harness()
    job_id = h.new_job(require_approval=True)
    job = h.run(job_id)
    assert job.phase is Phase.AWAITING_APPROVAL and job.approval_requested_at
    calls_before = len(h.llm.requests)
    job.approve()
    h.jobs.save(job)
    job = h.run(job_id)
    assert job.phase is Phase.COMPLETED and job.success
    assert h.llm.calls("AnalysisLLM") == 1 and h.llm.calls("PlanLLM") == 1  # no rework
    assert len(h.llm.requests) > calls_before


# O3
def test_reject_with_feedback_replans_once_then_cancels(harness):
    h = harness()
    job_id = h.new_job(require_approval=True)
    job = h.run(job_id)
    job.reject("Please split the routes into routers/todos.py.")
    h.jobs.save(job)
    job = h.run(job_id)
    assert job.phase is Phase.AWAITING_APPROVAL and job.plan.revision == 2
    planner_prompt = h.llm.requests[-1].messages[0].text
    assert "split the routes into routers/todos.py" in planner_prompt
    job.reject("Still not good.")
    h.jobs.save(job)
    assert h.jobs.get(job_id).phase is Phase.CANCELLED


# O4
def test_independent_steps_run_in_parallel(harness):
    h = harness(
        FakeLLM(plan=PARALLEL_PLAN, step_files=PARALLEL_FILES, step_delay=0.3), parallel_steps=2
    )
    job = h.run(h.new_job())
    assert job.success, job.errors
    assert h.llm.max_active == 2  # steps 1 and 2 overlapped
    step_events = [e.data for j, e in h.jobs.events if e.type == "step"]
    started_3 = next(
        i for i, d in enumerate(step_events) if d["id"] == 3 and d["status"] == "in_progress"
    )
    done = [
        i for i, d in enumerate(step_events) if d["status"] == "completed" and d["id"] in (1, 2)
    ]
    assert max(done) < started_3  # step 3 waited for both dependencies


def test_sequential_when_parallelism_is_one(harness):
    h = harness(
        FakeLLM(plan=PARALLEL_PLAN, step_files=PARALLEL_FILES, step_delay=0.05), parallel_steps=1
    )
    assert h.run(h.new_job()).success
    assert h.llm.max_active == 1


# O5
def test_broken_step_output_is_retried_with_check_feedback(harness):
    broken = REF["main.py"] + "\nresult = jsonify({})\n"
    plan = [
        {
            **PARALLEL_PLAN[2],
            "id": 1,
            "depends_on": [],
            "source_files": ["app.py", "models.py"],
            "target_files": ["main.py", "models.py"],
        }
    ]
    llm = FakeLLM(
        plan=plan,
        step_sequence={"main.py": [broken, REF["main.py"]]},
        step_files={"models.py": REF["models.py"]},
    )
    h = harness(llm)
    job = h.run(h.new_job())
    assert job.success, job.errors
    assert job.plan.step(1).attempts == 2
    retry_prompt = (
        [r for r in llm.requests if r.response_schema and r.response_schema.__name__ == "StepLLM"][
            -1
        ]
        .messages[0]
        .text
    )
    assert "F821" in retry_prompt and "jsonify" in retry_prompt


# O6
def test_step_failing_twice_fails_the_job_and_skips_dependents(harness):
    plan = [PARALLEL_PLAN[0], {**PARALLEL_PLAN[2], "depends_on": [1], "id": 2}]
    llm = FakeLLM(plan=plan, step_files={"models.py": "def broken(:\n"})
    h = harness(llm)
    job = h.run(h.new_job())
    assert job.phase is Phase.FAILED and not job.success
    assert job.plan.step(1).status is StepStatus.FAILED
    assert job.plan.step(2).status is StepStatus.SKIPPED
    assert job.current_files() == {}  # the failed step's output is hidden
    assert "Step 1" in job.errors[-1]
    assert h.episodes.recent("flask-fastapi", 1)[0].outcome == "failure"


# O7
def test_verification_failure_reexecutes_the_responsible_step_once(harness):
    missing_delete = REF["main.py"].split("@app.delete")[0]
    plan = [
        {
            **PARALLEL_PLAN[2],
            "id": 1,
            "depends_on": [],
            "target_files": ["main.py", "models.py"],
            "source_files": ["app.py", "models.py"],
        }
    ]
    llm = FakeLLM(
        plan=plan,
        step_sequence={"main.py": [missing_delete, REF["main.py"]]},
        step_files={"models.py": REF["models.py"]},
    )
    h = harness(llm)
    job = h.run(h.new_job())
    assert job.success, job.errors
    phases = h.jobs.phases(job.id)
    assert phases.count("execution") == 2 and phases.count("verification") == 2
    retry_prompt = (
        [r for r in llm.requests if r.response_schema and r.response_schema.__name__ == "StepLLM"][
            -1
        ]
        .messages[0]
        .text
    )
    assert "routes_preserved" in retry_prompt and "DELETE /todos/{todo_id}" in retry_prompt


def test_verification_still_failing_fails_without_llm_review(harness):
    missing_delete = REF["main.py"].split("@app.delete")[0]
    plan = [
        {
            **PARALLEL_PLAN[2],
            "id": 1,
            "depends_on": [],
            "target_files": ["main.py", "models.py"],
            "source_files": ["app.py", "models.py"],
        }
    ]
    llm = FakeLLM(plan=plan, step_files={"main.py": missing_delete, "models.py": REF["models.py"]})
    h = harness(llm)
    job = h.run(h.new_job())
    assert job.phase is Phase.FAILED and "Verification failed" in job.errors[-1]
    assert llm.calls("VerificationLLM") == 0
    assert not job.verification.checks_passed


def test_low_reviewer_confidence_completes_without_success(harness):
    h = harness(FakeLLM(confidence=5))
    job = h.run(h.new_job())
    assert job.phase is Phase.COMPLETED and not job.success
    assert job.verification.issues[0].message == "Needs review"


# O8 + D6
def test_budget_exceeded_fails_cleanly(harness):
    h = harness(job_llm_budget=2)
    job = h.run(h.new_job())
    assert job.phase is Phase.FAILED and "limit of 2 LLM calls" in job.errors[-1]
    assert job.llm_calls == 2


def test_daily_quota_mid_job_fails_with_reason(harness):
    h = harness(FakeLLM(fail={"StepLLM": LLMQuotaExceeded("day", 3600)}))
    job = h.run(h.new_job())
    assert job.phase is Phase.FAILED and "quota" in job.errors[-1]
    assert h.jobs.event_types(job.id)[-2:] == ["phase", "done"]


def test_invalid_plan_gets_one_repair_then_succeeds(harness):
    cyclic = [{**PARALLEL_PLAN[0], "depends_on": [2]}, {**PARALLEL_PLAN[1], "depends_on": [1]}]
    llm = FakeLLM(plan_sequence=[cyclic, None])
    h = harness(llm)
    job = h.run(h.new_job())
    assert job.success, job.errors
    assert llm.calls("PlanLLM") == 2
    repair = (
        [r for r in llm.requests if r.response_schema and r.response_schema.__name__ == "PlanLLM"][
            -1
        ]
        .messages[-1]
        .text
    )
    assert "cycle" in repair


def test_analyzer_tool_round_then_answer(harness):
    llm = FakeLLM(tool_first=True)
    h = harness(llm, max_tool_rounds=2)
    job = h.run(h.new_job())
    assert job.success
    final = next(
        r for r in llm.requests if r.response_schema and r.response_schema.__name__ == "AnalysisLLM"
    )
    notes = final.messages[1].text
    assert "Tool find_text returned" in notes and final.tools == []


def step_prompts(llm: FakeLLM) -> list[str]:
    return [
        r.messages[0].text
        for r in llm.requests
        if r.response_schema and r.response_schema.__name__ == "StepLLM"
    ]


# Cross-file consistency (found in the first real Gemini run: step 2 used the SOURCE
# models.py API while step 1 had already rewritten it).
def test_executor_sees_the_files_its_dependencies_migrated(harness):
    llm = FakeLLM(plan=PARALLEL_PLAN, step_files=PARALLEL_FILES)
    h = harness(llm, parallel_steps=1)
    assert h.run(h.new_job()).success
    by_step = {p.split("\n", 1)[0]: p for p in step_prompts(llm)}
    app_step = by_step["Execute step 3 of 3: Create app"]
    upstream = app_step.split("# Files already migrated by earlier steps")[1].split("# Current")[0]
    assert '<file path="models.py">' in upstream and '<file path="schemas.py">' in upstream
    models_step = by_step["Execute step 1 of 3: Create models"]
    assert "(none)" in models_step.split("# Files already migrated by earlier steps")[1]


def test_step_importing_a_name_its_dependency_does_not_define_is_retried(harness):
    wrong = REF["main.py"].replace("TodoStore", "TodoRepository")
    llm = FakeLLM(
        plan=PARALLEL_PLAN,
        step_files={k: v for k, v in PARALLEL_FILES.items() if k != "main.py"},
        step_sequence={"main.py": [wrong, REF["main.py"]]},
    )
    h = harness(llm)
    job = h.run(h.new_job())
    assert job.success, job.errors
    assert job.plan.step(3).attempts == 2
    assert "imports 'TodoRepository' from models.py" in step_prompts(llm)[-1]
