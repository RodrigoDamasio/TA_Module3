import dataclasses
import time
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


# ---- API (fake LLM, temp database, real background runner) ----------------------------

API_SETTINGS = {"rate_limit_jobs_per_minute": 100, "rate_limit_jobs_per_day": 1000}


class Api:
    def __init__(self, client, container, llm: FakeLLM) -> None:
        self.client, self.container, self.llm = client, container, llm

    def submit(self, pair: str = "flask-fastapi", approval: bool = False, **query) -> dict:
        source, target = pair.split("-")
        r = self.client.post(
            "/migrate",
            params=query,
            json={
                "files": [{"path": p, "content": c} for p, c in sample_files(pair).items()],
                "source_framework": source,
                "target_framework": target,
                "require_approval": approval,
            },
        )
        assert r.status_code in (200, 202), r.text
        return r.json()

    def wait_for(self, job_id: str, *phases: str, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            view = self.client.get(f"/migrations/{job_id}").json()
            if view["phase"] in phases:
                return view
            time.sleep(0.02)
        raise AssertionError(f"{job_id} never reached {phases}: {view['phase']}")


@pytest.fixture
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.dependencies import build_container
    from app.main import create_app

    clients = []

    def make(llm: FakeLLM | None = None, raise_errors: bool = True, **settings) -> Api:
        llm = llm or FakeLLM()
        s = dataclasses.replace(
            get_settings(),
            **(
                API_SETTINGS
                | {"llm_mode": "fake", "database_path": str(tmp_path / "api.db")}
                | settings
            ),
        )
        container = build_container(s, llm=llm)
        client = TestClient(
            create_app(s, container), raise_server_exceptions=raise_errors
        ).__enter__()
        clients.append(client)
        return Api(client, container, llm)

    yield make
    for client in clients:
        client.__exit__(None, None, None)
