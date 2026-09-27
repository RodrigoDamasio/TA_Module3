"""State machine, plan DAG, versions, rollback — 0 LLM calls."""

import itertools

import pytest

from app.domain.errors import InvalidPath, InvalidPlan, InvalidTransition
from app.domain.files import SourceFile, validate_path
from app.domain.job import _TRANSITIONS, MigrationJob, Phase, job_from_dict, job_to_dict
from app.domain.plan import Complexity, Plan, PlanStep, StepStatus
from app.domain.reports import Analysis, Check, VerificationReport


def step(id_, deps=(), targets=None, sources=("app.py",)):
    return PlanStep(
        id_,
        f"Step {id_}",
        "Do something useful here.",
        list(deps),
        Complexity.LOW,
        list(sources),
        list(targets or [f"f{id_}.py"]),
    )


def job(phase=Phase.ANALYSIS, steps=None):
    j = MigrationJob.create("flask-fastapi", [SourceFile("app.py", "x = 1\n")], True)
    j.phase = phase
    if steps is not None:
        j.plan = Plan(steps)
        j.plan.validate(8)
    j.pop_events()
    return j


# D1
@pytest.mark.parametrize("current, target", list(itertools.product(Phase, Phase)))
def test_only_allowed_transitions(current, target):
    j = job(current)
    if target in _TRANSITIONS.get(current, set()):
        j.move_to(target)
        events = j.pop_events()
        assert j.phase is target and events[0].type == "phase"
        assert events[0].data["phase"] == target.value
    else:
        with pytest.raises(InvalidTransition):
            j.move_to(target)


# D2
@pytest.mark.parametrize(
    "steps, message",
    [
        ([], "no steps"),
        ([step(i) for i in range(1, 10)], "maximum is 8"),
        ([step(1), step(1)], "unique"),
        ([step(1, deps=[7])], "unknown"),
        ([step(1, deps=[1])], "itself"),
        ([step(1, deps=[2]), step(2, deps=[1])], "cycle"),
        ([step(1), step(2, targets=["f1.py"])], "both write"),
        ([PlanStep(1, "t", "description", [], Complexity.LOW, [], [])], "writes no files"),
    ],
)
def test_invalid_plans_are_rejected(steps, message):
    with pytest.raises(InvalidPlan, match=message):
        Plan(steps).validate(8)


def test_shared_target_is_fine_when_ordered():
    Plan([step(1), step(2, deps=[1], targets=["f1.py"])]).validate(8)


# D3
def test_ready_steps_follow_dependencies_and_failures_skip_dependents():
    j = job(Phase.EXECUTION, [step(1), step(2, [1]), step(3, [1]), step(4, [2, 3]), step(5)])
    assert [s.id for s in j.plan.ready_steps()] == [1, 5]
    j.start_step(1)
    j.complete_step(1, {"f1.py": "a = 1\n"})
    assert [s.id for s in j.plan.ready_steps()] == [2, 3, 5]
    j.start_step(2)
    j.fail_step(2, "boom")
    statuses = {s.id: s.status for s in j.plan.steps}
    assert statuses[2] is StepStatus.FAILED and statuses[4] is StepStatus.SKIPPED
    assert statuses[3] is StepStatus.PENDING


# D4
def test_versions_latest_visible_and_failed_step_output_hidden():
    j = job(Phase.EXECUTION, [step(1, targets=["main.py"]), step(2, [1], targets=["main.py"])])
    j.start_step(1)
    j.complete_step(1, {"main.py": "v1\n"})
    j.start_step(2)
    j.complete_step(2, {"main.py": "v2\n"})
    assert j.current_files() == {"main.py": "v2\n"}
    assert [v.version for v in j.versions] == [1, 2]
    j.reopen_step(2)
    assert j.current_files() == {"main.py": "v1\n"}
    assert j.plan.step(2).status is StepStatus.PENDING


# D5
@pytest.mark.parametrize("end", [Phase.COMPLETED, Phase.FAILED])
def test_rollback_restores_sources(end):
    j = job(Phase.EXECUTION, [step(1, targets=["main.py"])])
    j.start_step(1)
    j.complete_step(1, {"main.py": "migrated\n"})
    j.phase = end
    j.rollback()
    assert j.current_files() == {}
    assert j.sources[0].content == "x = 1\n"
    assert j.plan.step(1).status is StepStatus.ROLLED_BACK
    assert j.phase is Phase.ROLLED_BACK
    assert j.pop_events()[-1].type == "done"


@pytest.mark.parametrize("phase", [Phase.EXECUTION, Phase.AWAITING_APPROVAL, Phase.ROLLED_BACK])
def test_rollback_only_from_finished_jobs(phase):
    with pytest.raises(InvalidTransition):
        job(phase, [step(1)]).rollback()


def test_approval_and_rejection():
    j = job(Phase.AWAITING_APPROVAL, [step(1)])
    j.reject("Split step 1 into two.")
    assert j.phase is Phase.PLANNING and j.replans == 1
    assert j.rejection_feedback == "Split step 1 into two."
    j.phase = Phase.AWAITING_APPROVAL
    j.reject("Again")  # second rejection: no more replans
    assert j.phase is Phase.CANCELLED
    j2 = job(Phase.AWAITING_APPROVAL, [step(1)])
    j2.approve()
    assert j2.phase is Phase.EXECUTION
    with pytest.raises(InvalidTransition):
        j2.approve()


def test_success_needs_checks_and_confidence():
    j = job(Phase.VERIFICATION, [step(1)])
    j.set_verification(VerificationReport([Check("parses", True)], confidence=8, verdict="pass"))
    j.complete()
    assert j.success is True
    j2 = job(Phase.VERIFICATION, [step(1)])
    j2.set_verification(VerificationReport([Check("parses", True)], confidence=5))
    j2.complete()
    assert j2.success is False


def test_serialization_round_trip():
    j = job(Phase.EXECUTION, [step(1, targets=["main.py"]), step(2, [1])])
    j.set_analysis(Analysis("A Flask app with two routes.", ["app"], ["flask"], [], []))
    j.start_step(1)
    j.complete_step(1, {"main.py": "print(1)\n"}, notes="done")
    j.set_verification(VerificationReport([Check("parses", True, "", "main.py")], confidence=9))
    restored = job_from_dict(job_to_dict(j))
    assert job_to_dict(restored) == job_to_dict(j)
    assert restored.plan.step(1).status is StepStatus.COMPLETED


@pytest.mark.parametrize("path", ["../x.py", "/etc/x.py", "a\\b.py", "x.txt", "", "a/../../b.py"])
def test_invalid_paths(path):
    with pytest.raises(InvalidPath):
        validate_path(path)


@pytest.mark.parametrize(
    "path, clean",
    [("app.py", "app.py"), ("routes/users.js", "routes/users.js"), ("./x.py", "x.py")],
)
def test_valid_paths(path, clean):
    assert validate_path(path) == clean
