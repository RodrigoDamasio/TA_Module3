/** MigrationApp behaviors C1–C14 (FRONTEND_PLAN §8). API and EventSource are faked:
 * 0 network calls. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MigrationApp from "@/components/MigrationApp";
import PlanViewer from "@/components/PlanViewer";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { JobView } from "@/lib/schemas";
import { FakeEventSource } from "./fakeEventSource";
import { FRAMEWORKS, job, running, SAMPLES_LIST, sampleDetail, step, storedJob } from "./fixtures";

vi.mock("@/lib/api", async (original) => {
  const actual = await original<typeof import("@/lib/api")>();
  return {
    ...actual,
    listFrameworks: vi.fn(),
    listSamples: vi.fn(),
    getSample: vi.fn(),
    migrate: vi.fn(),
    getJob: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
    rollback: vi.fn(),
  };
});

const mocked = vi.mocked(api);
const JOB = "mig_abc123";

beforeEach(() => {
  vi.clearAllMocks();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  window.history.replaceState(null, "", "/");
  mocked.listFrameworks.mockResolvedValue(FRAMEWORKS);
  mocked.listSamples.mockResolvedValue(SAMPLES_LIST);
  mocked.migrate.mockResolvedValue({
    job_id: JOB,
    phase: "analysis",
    status_url: `/migrations/${JOB}`,
    events_url: `/migrations/${JOB}/events`,
  });
});

async function renderApp(initialJobId: string | null = null) {
  const user = userEvent.setup();
  render(<MigrationApp initialJobId={initialJobId} />);
  await screen.findByRole("option", { name: "Flask" });
  return user;
}

async function fillFile(user: ReturnType<typeof userEvent.setup>, path = "app.py", code = "x = 1") {
  await user.type(screen.getByLabelText("File 1 path"), path);
  fireEvent.change(screen.getByLabelText("File 1 content"), { target: { value: code } });
}

function source() {
  const s = FakeEventSource.instances.at(-1);
  if (!s) throw new Error("no EventSource opened");
  return s;
}

/** Opens a live job (resumed from ?job=) and returns its event source. */
async function openJob(view: JobView) {
  mocked.getJob.mockResolvedValue(view);
  const user = await renderApp(JOB);
  await screen.findByRole("heading", { name: "2. Progress" });
  return user;
}

describe("input", () => {
  it("C1: renders the pair, one file, approval on, the privacy notice; Migrate waits", async () => {
    await renderApp();
    expect(screen.getByLabelText("Source framework")).toHaveValue("flask");
    expect(screen.getByLabelText("Target framework")).toHaveValue("fastapi");
    expect(screen.getByLabelText("File 1 path")).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: /Require my approval/ })).toBeChecked();
    expect(screen.getByText(/sent to Google Gemini/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Migrate" })).toBeDisabled();
    expect(screen.getByText("Add at least one file: its path and code.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("C2: the source decides the targets and the accepted extensions", async () => {
    const user = await renderApp();
    await user.selectOptions(screen.getByLabelText("Source framework"), "python2");
    expect(screen.getByLabelText("Target framework")).toHaveValue("python3");
    await user.selectOptions(screen.getByLabelText("Source framework"), "express");
    expect(screen.getByLabelText("Target framework")).toHaveValue("fastapi");
    await fillFile(user, "app.py");
    expect(screen.getByRole("alert")).toHaveTextContent("accepts .cjs, .js, .mjs, .ts");
    expect(screen.getByRole("button", { name: "Migrate" })).toBeDisabled();
  });

  it("C3: limits files to 5 and explains invalid paths", async () => {
    const user = await renderApp();
    const add = screen.getByRole("button", { name: "Add file" });
    for (let i = 0; i < 4; i++) await user.click(add);
    expect(screen.getAllByRole("group", { name: /File \d/ })).toHaveLength(5);
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Remove file 5" }));
    expect(add).toBeEnabled();
    await fillFile(user, "../app.py");
    expect(screen.getByRole("alert")).toHaveTextContent("stay inside the project");
  });

  it("C4: uploads several files and refuses other types", async () => {
    await renderApp();
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    // fireEvent, not user.upload: userEvent would apply `accept` itself and hide notes.json
    fireEvent.change(input, {
      target: {
        files: [
          new File(["from flask import Flask"], "app.py"),
          new File(["x = 1"], "models.py"),
          new File(["{}"], "notes.json"),
        ],
      },
    });
    await waitFor(() => expect(screen.getByLabelText("File 2 path")).toHaveValue("models.py"));
    expect(screen.getByLabelText("File 1 path")).toHaveValue("app.py");
    expect(screen.getByRole("status")).toHaveTextContent("Not added (wrong type): notes.json.");
    expect(screen.getByRole("button", { name: "Migrate" })).toBeEnabled();
  });
});

describe("a live job", () => {
  it("C5: Migrate sends the project, sets ?job= and follows the job", async () => {
    let finish: (v: Awaited<ReturnType<typeof api.migrate>>) => void = () => {};
    mocked.migrate.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    mocked.getJob.mockResolvedValue(running("analysis"));
    const user = await renderApp();
    await fillFile(user, "./app.py", "print('hi')");
    await user.click(screen.getByRole("button", { name: "Migrate" }));
    expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled(); // no double submit
    await act(async () =>
      finish({
        job_id: JOB,
        phase: "analysis",
        status_url: `/migrations/${JOB}`,
        events_url: `/migrations/${JOB}/events`,
      }),
    );
    expect(mocked.migrate).toHaveBeenCalledWith({
      files: [{ path: "app.py", content: "print('hi')" }],
      source_framework: "flask",
      target_framework: "fastapi",
      require_approval: true,
    });
    expect(window.location.search).toBe(`?job=${JOB}`);
    await screen.findByRole("heading", { name: "2. Progress" });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(source().url).toBe(`http://localhost:8000/migrations/${JOB}/events`);
    expect(screen.getByRole("button", { name: "New migration" })).toBeInTheDocument();
  });

  it("C6: events move the stepper, fill the log and show the plan", async () => {
    await openJob(running("analysis", { plan: null }));
    const plan = storedJob("flask_todo").plan!;
    mocked.getJob.mockResolvedValue(running("awaiting_approval"));
    act(() => {
      source().emit("phase", { phase: "planning" }, 2);
      source().emit(
        "plan",
        { ...plan, steps: plan.steps.map((s) => ({ ...s, status: "pending" })) },
        3,
      );
      source().emit("phase", { phase: "awaiting_approval" }, 4);
    });
    const activity = screen.getByRole("list", { name: "Activity" });
    expect(within(activity).getByText("Plan ready — waiting for your approval.")).toBeVisible();
    const current = screen.getByRole("listitem", { current: "step" });
    expect(current).toHaveTextContent("Awaiting approval");
    expect(screen.getByRole("heading", { name: "3. Migration plan" })).toBeInTheDocument();
    expect(screen.getAllByText("Pending")).toHaveLength(plan.steps.length);
    expect(await screen.findByRole("heading", { name: "Your approval is needed" })).toBeVisible();
  });

  it("C7: approve runs the plan; parallel steps show together", async () => {
    await openJob(running("awaiting_approval"));
    mocked.approve.mockResolvedValue(running("execution"));
    mocked.getJob.mockResolvedValue(running("execution"));
    await userEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    expect(mocked.approve).toHaveBeenCalledWith(JOB);
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Your approval is needed" })).toBeNull(),
    );
    const first = running("execution").plan!.steps[0];
    act(() => source().emit("step", { ...first, status: "in_progress", attempts: 1 }, 7));
    const activity = screen.getByRole("list", { name: "Activity" });
    expect(within(activity).getByText(/Step 1 \(.*\): in progress/)).toBeInTheDocument();

    const parallel = {
      revision: 1,
      steps: [
        step(1, { status: "completed" }),
        step(2, { depends_on: [1], status: "in_progress" }),
        step(3, { depends_on: [1], status: "in_progress" }),
      ],
    };
    const { container } = render(<PlanViewer plan={parallel} />);
    const viewer = within(container);
    expect(viewer.getByText("Wave 2 · 2 steps can run in parallel")).toBeInTheDocument();
    expect(viewer.getAllByText("In progress")).toHaveLength(2);
    expect(viewer.getByText("runs in parallel with 3")).toBeInTheDocument();
  });

  it("C8: reject with feedback replans once, then only cancel is left", async () => {
    const user = await openJob(running("awaiting_approval"));
    mocked.reject.mockResolvedValue(running("planning"));
    mocked.getJob.mockResolvedValue(running("planning"));
    await user.type(screen.getByLabelText(/Feedback for a new plan/), "Use one step only.");
    await user.click(screen.getByRole("button", { name: "Reject and replan" }));
    expect(mocked.reject).toHaveBeenCalledWith(JOB, "Use one step only.");

    const plan = storedJob("flask_todo").plan!;
    const replanned = running("awaiting_approval", {
      plan: { ...plan, revision: 2 },
      meta: { ...running("planning").meta, replans: 1 },
    });
    mocked.getJob.mockResolvedValue(replanned);
    act(() => source().emit("phase", { phase: "awaiting_approval" }, 12));
    expect(await screen.findByText("Plan revision 2")).toBeInTheDocument();
    expect(screen.getByLabelText(/Feedback for a new plan/)).toBeDisabled();
    expect(screen.getByText(/No replans left/)).toBeInTheDocument();
    mocked.reject.mockResolvedValue({ ...replanned, phase: "cancelled" });
    await user.click(screen.getByRole("button", { name: "Reject and cancel" }));
    expect(mocked.reject).toHaveBeenLastCalledWith(JOB, null);
  });
});

describe("results", () => {
  it("C9: a completed job shows verification, file tabs and the diff", async () => {
    const user = await openJob(job());
    expect(FakeEventSource.instances).toHaveLength(0); // finished jobs need no stream
    expect(screen.getByText(/Migration verified · confidence 10\/10/)).toBeInTheDocument();
    expect(screen.getByText("Every route preserved")).toBeInTheDocument();
    expect(screen.getByText("Imports between files resolve")).toBeInTheDocument();
    const tabs = screen.getByRole("tablist", { name: "Migrated files" });
    const fileTabs = within(tabs).getAllByRole("tab");
    expect(fileTabs.map((t) => t.textContent)).toEqual([
      expect.stringMatching(/^main\.py\s+\+\d+ −\d+$/),
      expect.stringMatching(/^models\.py\s+\+\d+ −\d+$/),
    ]);
    const compare = screen.getByLabelText("Compare with");
    expect(within(compare).getAllByRole("option")[0]).toHaveTextContent("Source app.py");
    expect(screen.getAllByText("added").length).toBeGreaterThan(0); // +/− markers have text
    await user.click(screen.getByRole("tab", { name: "Code" }));
    expect(screen.queryByLabelText("Compare with")).toBeNull();
    fileTabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(within(tabs).getByRole("tab", { selected: true })).toHaveTextContent("models.py");
    expect(screen.getByLabelText("Compare with")).toHaveValue("source:models.py");
  });

  it("C10: a failed step shows its error, skipped dependents and rollback", async () => {
    const base = running("failed");
    const [first, second] = base.plan!.steps;
    await openJob({
      ...base,
      errors: ["Step 1 (Migrate data models) failed: models.py:3 F821 undefined name 'x'"],
      plan: {
        ...base.plan!,
        steps: [
          { ...first, status: "failed", attempts: 2, error: "models.py:3 F821 undefined name 'x'" },
          { ...second, status: "skipped" },
        ],
      },
    });
    expect(screen.getByText(/Migration not verified/)).toBeInTheDocument();
    expect(screen.getAllByText(/F821 undefined name/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("retried 1×")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roll back" })).toBeInTheDocument();
    const stepper = screen.getByRole("heading", { name: "2. Progress" }).closest("section")!;
    expect(within(stepper).getByText("Execution").parentElement).toHaveTextContent(
      "(stopped here)",
    );
  });

  it("C11: rollback asks first, then hides every file and keeps the history", async () => {
    const done = job();
    const user = await openJob(done);
    const rolledBack: JobView = {
      ...done,
      phase: "rolled_back",
      success: false,
      migrated_files: [],
      history: done.migrated_files.map((f) => ({ ...f, hidden: true })),
    };
    mocked.rollback.mockResolvedValue(rolledBack);
    mocked.getJob.mockResolvedValue(rolledBack);
    await user.click(screen.getByRole("button", { name: "Roll back" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mocked.rollback).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Roll back" }));
    await user.click(screen.getByRole("button", { name: "Confirm rollback" }));
    expect(mocked.rollback).toHaveBeenCalledWith(JOB);
    expect(await screen.findByText(/every generated file is hidden/)).toBeInTheDocument();
    expect(screen.getByText(/Migration rolled back/)).toBeInTheDocument();
    expect(screen.getByText("Version history (2 hidden)")).toBeInTheDocument();
  });
});

describe("samples, errors and resilience", () => {
  it("C12: a sample replays its stored job with 0 LLM calls, then can run for real", async () => {
    mocked.getSample.mockResolvedValue(sampleDetail());
    mocked.getJob.mockResolvedValue(running("analysis"));
    const user = await renderApp();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await user.selectOptions(screen.getByLabelText("Try a sample"), "flask_todo");
    expect(await screen.findByText(/Stored result — replay/)).toBeInTheDocument();
    expect(screen.getByLabelText("File 1 path")).toHaveValue("app.py");
    expect(screen.getByLabelText("File 2 path")).toHaveValue("models.py");
    for (let i = 0; i < 12; i++) await act(async () => vi.advanceTimersByTime(700)); // frame by frame
    expect(screen.getByText(/Migration verified/)).toBeInTheDocument();
    expect(mocked.migrate).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Roll back" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Run it for real" }));
    expect(mocked.migrate).toHaveBeenCalledTimes(1);
    expect(mocked.migrate.mock.calls[0][0].files.map((f) => f.path)).toEqual([
      "app.py",
      "models.py",
    ]);
  });

  it("C13a: 422 field errors are listed", async () => {
    mocked.migrate.mockRejectedValue(
      new ApiError("validation", "The request body has 1 invalid field.", undefined, [
        "File 1 content: Must not be empty.",
      ]),
    );
    const user = await renderApp();
    await fillFile(user);
    await user.click(screen.getByRole("button", { name: "Migrate" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("File 1 content: Must not be empty.");
  });

  it("C13b: 429 and 503 disable Migrate until the countdown ends", async () => {
    mocked.migrate.mockRejectedValue(
      new ApiError("rate_limited", "You started too many migrations in a short time.", 3),
    );
    const user = await renderApp();
    await fillFile(user);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await user.click(screen.getByRole("button", { name: "Migrate" }));
    expect(await screen.findByText(/You can try again in 3 s/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Migrate" })).toBeDisabled();
    await act(async () => vi.advanceTimersByTime(4000));
    expect(screen.getByRole("button", { name: "Migrate" })).toBeEnabled();

    mocked.migrate.mockRejectedValue(
      new ApiError("quota", "Today's free AI quota is used up. The samples still work.", 18_000),
    );
    await user.click(screen.getByRole("button", { name: "Migrate" }));
    expect(await screen.findByText(/try again in about 5 h/)).toBeInTheDocument();
  });

  it("C13c: a 409 on approve refetches and explains", async () => {
    await openJob(running("awaiting_approval"));
    mocked.approve.mockRejectedValue(
      new ApiError("conflict", "The migration already moved on — showing its current state."),
    );
    mocked.getJob.mockResolvedValue(running("cancelled"));
    await userEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    expect(await screen.findByText(/already moved on/)).toBeInTheDocument();
    expect(await screen.findByText(/Migration cancelled/)).toBeInTheDocument();
  });

  it("C13d: an unknown ?job= shows that it no longer exists", async () => {
    mocked.getJob.mockRejectedValue(new ApiError("not_found", "This migration no longer exists."));
    const user = await renderApp(JOB);
    expect(await screen.findByText("This migration no longer exists.")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "New migration" });
    await user.click(buttons[buttons.length - 1]);
    expect(screen.getByRole("button", { name: "Migrate" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("C14: a lost stream falls back to polling until the job ends", async () => {
    await openJob(running("execution"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => source().fail());
    expect(screen.getByText(/Live updates interrupted/)).toBeInTheDocument();
    mocked.getJob.mockResolvedValue(job());
    await act(async () => vi.advanceTimersByTime(3500));
    expect(await screen.findByText(/Migration verified/)).toBeInTheDocument();
    const calls = mocked.getJob.mock.calls.length;
    await act(async () => vi.advanceTimersByTime(10_000));
    expect(mocked.getJob.mock.calls.length).toBe(calls); // polling stopped
  });
});
