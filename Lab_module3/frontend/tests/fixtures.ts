/** Test data: the backend's REAL stored results (samples/results/*.json) plus builders.
 * Parsing them with the Zod schemas also proves the schemas match the backend. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Framework, JobView, Sample, SampleDetail, Step } from "@/lib/schemas";
import { JobViewSchema } from "@/lib/schemas";

const RESULTS = join(__dirname, "..", "..", "backend", "samples", "results");
const SAMPLES = join(__dirname, "..", "..", "backend", "samples");

export function storedJob(sample: string): JobView {
  return JobViewSchema.parse(JSON.parse(readFileSync(join(RESULTS, `${sample}.json`), "utf8")));
}

export function sampleFile(sample: string, path: string): string {
  return readFileSync(join(SAMPLES, sample, path), "utf8");
}

export const FRAMEWORKS: Framework[] = [
  {
    id: "flask-fastapi",
    source: "flask",
    target: "fastapi",
    source_name: "Flask",
    target_name: "FastAPI",
    source_language: "python",
    description: "Flask app → FastAPI app.",
    source_extensions: [".py"],
  },
  {
    id: "express-fastapi",
    source: "express",
    target: "fastapi",
    source_name: "Express",
    target_name: "FastAPI",
    source_language: "javascript",
    description: "Express app → FastAPI app.",
    source_extensions: [".cjs", ".js", ".mjs", ".ts"],
  },
  {
    id: "python2-python3",
    source: "python2",
    target: "python3",
    source_name: "Python 2",
    target_name: "Python 3",
    source_language: "python",
    description: "Python 2 → Python 3.",
    source_extensions: [".py"],
  },
];

export const SAMPLES_LIST: Sample[] = [
  {
    id: "flask_todo",
    title: "Flask to-do API",
    source_framework: "flask",
    target_framework: "fastapi",
    description: "Two files.",
    has_result: true,
  },
];

export function sampleDetail(): SampleDetail {
  return {
    ...SAMPLES_LIST[0],
    files: [
      { path: "app.py", content: sampleFile("flask_todo", "app.py") },
      { path: "models.py", content: sampleFile("flask_todo", "models.py") },
    ],
    result: storedJob("flask_todo"),
  };
}

export function step(id: number, overrides: Partial<Step> = {}): Step {
  return {
    id,
    title: `Step ${id}`,
    description: `Do step ${id}.`,
    depends_on: [],
    complexity: "low",
    source_files: ["app.py"],
    target_files: [`out${id}.py`],
    status: "pending",
    attempts: 0,
    notes: null,
    error: null,
    ...overrides,
  };
}

/** A job in any phase, built from the real flask_todo result. */
export function job(overrides: Partial<JobView> = {}): JobView {
  return { ...storedJob("flask_todo"), job_id: "mig_abc123", ...overrides };
}

export function running(phase: JobView["phase"], overrides: Partial<JobView> = {}): JobView {
  const base = storedJob("flask_todo");
  return {
    ...base,
    job_id: "mig_abc123",
    phase,
    success: false,
    require_approval: true,
    verification: null,
    migrated_files: [],
    history: [],
    plan: base.plan && {
      ...base.plan,
      steps: base.plan.steps.map((s) => ({ ...s, status: "pending", attempts: 0 })),
    },
    meta: { ...base.meta, finished_at: null, approval_requested_at: new Date().toISOString() },
    ...overrides,
  };
}
