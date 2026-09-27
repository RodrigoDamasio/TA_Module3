from dataclasses import dataclass, field


@dataclass
class Analysis:
    summary: str
    components: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    file: str | None = None  # the file responsible, when one is


@dataclass
class VerificationIssue:
    severity: str
    file: str
    line: int | None
    message: str


@dataclass
class VerificationReport:
    checks: list[Check]
    issues: list[VerificationIssue] = field(default_factory=list)
    confidence: int = 0
    verdict: str = "fail"

    MIN_CONFIDENCE = 7

    @property
    def checks_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def passed(self) -> bool:
        return self.checks_passed and self.confidence >= self.MIN_CONFIDENCE
