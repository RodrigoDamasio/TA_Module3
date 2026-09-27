import dataclasses
from pathlib import Path

import pytest
from fakes import FakeLLM, MemoryEpisodes, MemoryJobs

from app.application.orchestrator import Orchestrator
from app.application.prompts import PromptLibrary
from app.config import get_settings
from app.domain.files import SourceFile
from app.domain.job import MigrationJob

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FOR_PAIR = {
    "flask-fastapi": "flask_todo",
    "express-fastapi": "express_users",
    "django-fastapi": "django_articles",
    "python2-python3": "py2_report",
}


def load(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): p.read_text() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def sample_files(pair: str) -> dict[str, str]:
    return load(ROOT / "samples" / SAMPLE_FOR_PAIR[pair])


def reference_files(pair: str) -> dict[str, str]:
    return load(ROOT / "tests" / "fixtures" / SAMPLE_FOR_PAIR[pair])


class Harness:
    def __init__(self, llm: FakeLLM, **settings) -> None:
        self.llm = llm
        self.jobs = MemoryJobs()
        self.episodes = MemoryEpisodes()
        self.settings = dataclasses.replace(get_settings(), **settings)
        self.orchestrator = Orchestrator(
            self.jobs, self.episodes, llm, PromptLibrary(), self.settings
        )

    def new_job(self, pair: str = "flask-fastapi", require_approval: bool = False) -> str:
        sources = [SourceFile(p, c) for p, c in sample_files(pair).items()]
        job = MigrationJob.create(pair, sources, require_approval)
        self.jobs.create(job)
        return job.id

    def run(self, job_id: str) -> MigrationJob:
        self.orchestrator.run(job_id)
        return self.jobs.get(job_id)


@pytest.fixture
def harness():
    def make(llm: FakeLLM | None = None, **settings) -> Harness:
        return Harness(llm or FakeLLM(), **settings)

    return make
