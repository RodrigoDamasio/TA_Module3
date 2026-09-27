"""The migration plan (course: Planning agent pattern) and its DAG rules."""

from dataclasses import dataclass, field
from enum import StrEnum

from .errors import InvalidPlan


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


class Complexity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PlanStep:
    id: int
    title: str
    description: str
    depends_on: list[int]
    complexity: Complexity
    source_files: list[str]
    target_files: list[str]
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    notes: str | None = None
    error: str | None = None


@dataclass
class Plan:
    steps: list[PlanStep]
    revision: int = 1
    _ancestors: dict[int, set[int]] = field(default_factory=dict, repr=False, compare=False)

    def step(self, step_id: int) -> PlanStep:
        return next(s for s in self.steps if s.id == step_id)

    def validate(self, max_steps: int) -> None:
        if not self.steps:
            raise InvalidPlan("The plan has no steps.")
        if len(self.steps) > max_steps:
            raise InvalidPlan(f"The plan has {len(self.steps)} steps; the maximum is {max_steps}.")
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise InvalidPlan("Step ids must be unique.")
        for s in self.steps:
            unknown = set(s.depends_on) - set(ids)
            if unknown:
                raise InvalidPlan(f"Step {s.id} depends on unknown steps {sorted(unknown)}.")
            if s.id in s.depends_on:
                raise InvalidPlan(f"Step {s.id} depends on itself.")
            if not s.target_files:
                raise InvalidPlan(f"Step {s.id} writes no files.")
        self._ancestors = self._compute_ancestors()  # raises on cycles
        self._check_parallel_safety()

    def _compute_ancestors(self) -> dict[int, set[int]]:
        deps = {s.id: set(s.depends_on) for s in self.steps}
        ancestors: dict[int, set[int]] = {}
        visiting: set[int] = set()

        def visit(node: int) -> set[int]:
            if node in ancestors:
                return ancestors[node]
            if node in visiting:
                raise InvalidPlan(f"The plan has a dependency cycle through step {node}.")
            visiting.add(node)
            result: set[int] = set()
            for parent in deps[node]:
                result |= {parent} | visit(parent)
            visiting.discard(node)
            ancestors[node] = result
            return result

        for s in self.steps:
            visit(s.id)
        return ancestors

    def _check_parallel_safety(self) -> None:
        """Two steps that may run at the same time must never write the same file."""
        for i, a in enumerate(self.steps):
            for b in self.steps[i + 1 :]:
                shared = set(a.target_files) & set(b.target_files)
                ordered = a.id in self._ancestors[b.id] or b.id in self._ancestors[a.id]
                if shared and not ordered:
                    raise InvalidPlan(
                        f"Steps {a.id} and {b.id} both write {sorted(shared)} but neither "
                        "depends on the other."
                    )

    def ready_steps(self) -> list[PlanStep]:
        done = {s.id for s in self.steps if s.status is StepStatus.COMPLETED}
        return [
            s for s in self.steps if s.status is StepStatus.PENDING and set(s.depends_on) <= done
        ]

    def dependents(self, step_id: int) -> list[PlanStep]:
        if not self._ancestors:
            self._ancestors = self._compute_ancestors()
        return [s for s in self.steps if step_id in self._ancestors[s.id]]

    def is_finished(self) -> bool:
        return all(
            s.status is not StepStatus.PENDING and s.status is not StepStatus.IN_PROGRESS
            for s in self.steps
        )
