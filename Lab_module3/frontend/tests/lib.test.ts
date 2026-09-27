import { describe, expect, it } from "vitest";
import { compareOptions } from "@/lib/compare";
import { fold, lineDiff, sideBySide, stats } from "@/lib/diff";
import { checkProject, draftFile, normalizePath, pathError, readUploads } from "@/lib/files";
import { stages, stoppedAt } from "@/lib/phases";
import { dependencyText, waves } from "@/lib/plan";
import { replayFrames } from "@/lib/replay";
import { job, running, step, storedJob } from "./fixtures";

describe("stored backend results", () => {
  it.each(["flask_todo", "express_users", "django_articles", "py2_report"])(
    "%s parses with the JobView schema",
    (sample) => {
      const view = storedJob(sample);
      expect(view.success).toBe(true);
      expect(view.migrated_files.length).toBeGreaterThan(0);
    },
  );
});

describe("files", () => {
  const py = [".py"];
  it("validates paths like the backend", () => {
    expect(pathError("app.py", py)).toBeNull();
    expect(pathError("pkg/app.py", py)).toBeNull();
    expect(pathError("./app.py", py)).toBeNull();
    expect(pathError("", py)).toMatch(/Enter a file path/);
    expect(pathError("../x.py", py)).toMatch(/inside the project/);
    expect(pathError("a//b.py", py)).toMatch(/inside the project/);
    expect(pathError("/etc/x.py", py)).toMatch(/relative/);
    expect(pathError("a\\b.py", py)).toMatch(/Use \//);
    expect(pathError("app.js", py)).toMatch(/accepts \.py/);
    expect(pathError(`${"a".repeat(120)}.py`, py)).toMatch(/120 characters/);
    expect(normalizePath(" ./././a.py ")).toBe("a.py");
  });

  it("checks the whole project", () => {
    const ok = checkProject([draftFile("app.py", "x = 1")], [".py"]);
    expect(ok.problem).toBeNull();
    expect(checkProject([], [".py"]).problem).toMatch(/at least one/);
    const pristine = checkProject([draftFile()], [".py"]);
    expect(pristine.problem).toMatch(/at least one/);
    expect(pristine.fileErrors).toEqual({});
    const oneBlank = checkProject([draftFile("a.py", "x"), draftFile()], [".py"]);
    expect(oneBlank.problem).toBe("Fill in or remove the empty file.");
    const dup = [draftFile("a.py", "x"), draftFile("./a.py", "y")];
    const dupCheck = checkProject(dup, [".py"]);
    expect(Object.values(dupCheck.fileErrors)).toEqual(["Another file already has this path."]);
    expect(dupCheck.problem).toMatch(/Fix the highlighted/);
    const empty = checkProject([draftFile("a.py", "  ")], [".py"]);
    expect(Object.values(empty.fileErrors)).toEqual(["Add the file's content."]);
    const six = Array.from({ length: 6 }, (_, i) => draftFile(`f${i}.py`, "x"));
    expect(checkProject(six, [".py"]).problem).toMatch(/At most 5/);
    const big = checkProject([draftFile("a.py", "x".repeat(30_001))], [".py"]);
    expect(big.problem).toMatch(/30,001 characters; the limit is 30,000/);
  });

  it("reads uploads and refuses other types", async () => {
    const files = [new File(["x = 1"], "app.py"), new File(["{}"], "data.json")];
    const { files: added, refused } = await readUploads(files, [".py"]);
    expect(added.map((f) => [f.path, f.content])).toEqual([["app.py", "x = 1"]]);
    expect(refused).toEqual(["data.json"]);
  });
});

describe("diff", () => {
  const before = "a\nb\nc\n";
  const after = "a\nB\nc\nd\n";

  it("numbers rows and counts changes", () => {
    const rows = lineDiff(before, after);
    expect(rows.map((r) => [r.kind, r.oldNo, r.newNo, r.text])).toEqual([
      ["same", 1, 1, "a"],
      ["del", 2, null, "b"],
      ["add", null, 2, "B"],
      ["same", 3, 3, "c"],
      ["add", null, 4, "d"],
    ]);
    expect(stats(rows)).toEqual({ added: 2, removed: 1 });
  });

  it("pairs removals with additions side by side", () => {
    const pairs = sideBySide(lineDiff(before, after));
    expect(pairs.map((p) => [p.left?.text ?? null, p.right?.text ?? null])).toEqual([
      ["a", "a"],
      ["b", "B"],
      ["c", "c"],
      [null, "d"],
    ]);
  });

  it("folds long unchanged runs but keeps context around changes", () => {
    const lines = Array.from({ length: 20 }, (_, i) => `l${i}`);
    const rows = lineDiff(lines.join("\n"), [...lines.slice(0, 19), "changed"].join("\n"));
    const items = fold(rows);
    expect(items[0]).toMatchObject({ kind: "fold" });
    expect(items[0].kind === "fold" && items[0].rows).toHaveLength(16);
    expect(items.slice(1).map((r) => r.kind)).toEqual(["same", "same", "same", "del", "add"]);
    expect(fold(lineDiff("a\nb", "a\nc"))).toHaveLength(3); // short runs are never folded
  });
});

describe("plan", () => {
  it("groups steps into waves that may run in parallel", () => {
    const steps = [
      step(1),
      step(2, { depends_on: [1] }),
      step(3, { depends_on: [1] }),
      step(4, { depends_on: [2, 3] }),
    ];
    const groups = waves(steps);
    expect(groups.map((w) => w.map((s) => s.id))).toEqual([[1], [2, 3], [4]]);
    expect(dependencyText(steps[1], groups[1])).toEqual(["after 1", "runs in parallel with 3"]);
    expect(dependencyText(steps[0], groups[0])).toEqual([]);
  });

  it("never loops on a cycle or an unknown dependency", () => {
    const groups = waves([step(1, { depends_on: [2] }), step(2, { depends_on: [1, 9] })]);
    expect(groups.flat()).toHaveLength(2);
  });
});

describe("phases", () => {
  it("marks done, current and upcoming phases", () => {
    const list = stages(running("awaiting_approval"));
    expect(list.map((s) => [s.phase, s.state])).toEqual([
      ["analysis", "done"],
      ["planning", "done"],
      ["awaiting_approval", "current"],
      ["execution", "upcoming"],
      ["verification", "upcoming"],
      ["completed", "upcoming"],
    ]);
  });

  it("skips the approval phase when it is not required", () => {
    const list = stages(job());
    expect(list.map((s) => s.phase)).not.toContain("awaiting_approval");
    expect(list.every((s) => s.state === "done")).toBe(true);
  });

  it("shows where a failed or cancelled job stopped", () => {
    const failedPlan = running("failed", {
      analysis: storedJob("flask_todo").analysis,
      plan: null,
    });
    expect(stoppedAt(failedPlan)).toBe("planning");
    expect(stoppedAt(running("failed", { analysis: null }))).toBe("analysis");
    expect(stoppedAt(running("failed"))).toBe("execution");
    expect(stoppedAt(running("cancelled"))).toBe("awaiting_approval");
    expect(stoppedAt({ ...job(), phase: "failed" })).toBe("verification");
    const list = stages(running("failed"));
    expect(list.map((s) => s.state)).toEqual([
      "done",
      "done",
      "done",
      "failed",
      "skipped",
      "failed",
    ]);
  });
});

describe("compare options", () => {
  it("offers the same-path source, the step's sources, and earlier versions", () => {
    const view = job();
    const main = view.migrated_files.find((f) => f.path === "main.py")!;
    const models = view.migrated_files.find((f) => f.path === "models.py")!;
    expect(compareOptions(main, view).map((o) => o.label)[0]).toMatch(
      /Source app\.py \(read by step/,
    );
    expect(compareOptions(models, view)[0].label).toBe("Source models.py (same path)");

    const withHistory = {
      ...view,
      history: [
        { ...models, version: 1, hidden: true },
        { ...models, version: 2, hidden: false },
      ],
    };
    const labels = compareOptions({ ...models, version: 2 }, withHistory).map((o) => o.label);
    expect(labels).toContain("Version 1 (step 1, discarded)");
  });

  it("falls back to every source when the step is unknown", () => {
    const view = job({ plan: null });
    const main = view.migrated_files.find((f) => f.path === "main.py")!;
    expect(compareOptions(main, view).map((o) => o.id)).toEqual([
      "source:app.py",
      "source:models.py",
    ]);
  });
});

describe("replay", () => {
  it("animates a stored job phase by phase and ends on the real result", () => {
    const stored = storedJob("flask_todo");
    const frames = replayFrames(stored);
    expect(frames[0].view.phase).toBe("analysis");
    expect(frames[0].view.migrated_files).toEqual([]);
    expect(frames.some((f) => f.view.plan?.steps.some((s) => s.status === "in_progress"))).toBe(
      true,
    );
    expect(frames.at(-1)!.view).toBe(stored);
    expect(frames.at(-1)!.message).toBe("Migration completed.");
    // steps × 2 + analysis + planning + plan ready + verification + final
    expect(frames).toHaveLength(stored.plan!.steps.length * 2 + 5);
  });
});
