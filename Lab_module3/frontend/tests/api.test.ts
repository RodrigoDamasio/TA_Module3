import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  approve,
  eventsUrl,
  fieldLabel,
  getJob,
  getSample,
  listFrameworks,
  listSamples,
  migrate,
  reject,
  rollback,
} from "@/lib/api";
import { FRAMEWORKS, job, SAMPLES_LIST, sampleDetail } from "./fixtures";

const PROBLEM = "application/problem+json";

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fn = vi.fn().mockResolvedValue(
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "Content-Type": status >= 400 ? PROBLEM : "application/json", ...headers },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function problem(slug: string, status: number, extra: object = {}) {
  return {
    type: `http://x/problems/${slug}`,
    title: "t",
    status,
    detail: `detail ${slug}`,
    ...extra,
  };
}

async function errorOf(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    if (err instanceof ApiError) return err;
    throw err;
  }
  throw new Error("expected an ApiError");
}

const BODY = {
  files: [{ path: "app.py", content: "x = 1" }],
  source_framework: "flask",
  target_framework: "fastapi",
  require_approval: true,
};

describe("requests", () => {
  it("posts the migration and parses the 202 body", async () => {
    const fetchFn = mockFetch(202, {
      job_id: "mig_1",
      phase: "analysis",
      status_url: "/migrations/mig_1",
      events_url: "/migrations/mig_1/events",
    });
    const accepted = await migrate(BODY);
    expect(accepted.job_id).toBe("mig_1");
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://localhost:8000/migrate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(BODY);
  });

  it("uses NEXT_PUBLIC_API_URL without a trailing slash", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com/");
    const fetchFn = mockFetch(200, FRAMEWORKS);
    await listFrameworks();
    expect(fetchFn.mock.calls[0][0]).toBe("https://api.example.com/frameworks");
    expect(eventsUrl("mig_1")).toBe("https://api.example.com/migrations/mig_1/events");
  });

  it("reads jobs with their history and runs the actions", async () => {
    const view = job();
    const fetchFn = mockFetch(200, view);
    await getJob("mig_1");
    expect(fetchFn.mock.calls[0][0]).toMatch(/\/migrations\/mig_1\?include_history=true$/);
    for (const [call, path] of [
      [() => approve("mig_1"), "/approve"],
      [() => rollback("mig_1"), "/rollback"],
    ] as const) {
      const f = mockFetch(200, view);
      await call();
      expect(f.mock.calls[0][0]).toMatch(new RegExp(`${path}$`));
    }
    const f = mockFetch(200, view);
    await reject("mig_1", "one step");
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ feedback: "one step" });
  });

  it("lists samples and loads one", async () => {
    mockFetch(200, SAMPLES_LIST);
    expect(await listSamples()).toEqual(SAMPLES_LIST);
    mockFetch(200, sampleDetail());
    expect((await getSample("flask_todo")).result?.success).toBe(true);
  });
});

describe("errors (FRONTEND_PLAN §6)", () => {
  it.each([
    [400, problem("malformed-request", 400), "validation"],
    [422, problem("unsupported-migration", 422), "unsupported"],
    [413, problem("input-too-large", 413), "too_large"],
    [404, problem("job-not-found", 404), "not_found"],
    [409, problem("invalid-transition", 409), "conflict"],
    [500, problem("internal-error", 500), "server"],
    [502, "<html>bad gateway</html>", "server"],
  ])("%i → %s", async (status, body, kind) => {
    mockFetch(status, body);
    expect((await errorOf(migrate(BODY))).kind).toBe(kind);
  });

  it("maps field errors to readable labels", async () => {
    mockFetch(
      422,
      problem("validation-error", 422, {
        errors: [
          { detail: "Must not be empty.", pointer: "#/files/1/content" },
          { detail: "Bad path.", pointer: "#/files" },
          { detail: "Required.", pointer: "#/source_framework" },
        ],
      }),
    );
    const err = await errorOf(migrate(BODY));
    expect(err.kind).toBe("validation");
    expect(err.fieldErrors).toEqual([
      "File 2 content: Must not be empty.",
      "Files: Bad path.",
      "Source framework: Required.",
    ]);
    expect(fieldLabel("#")).toBe("Request");
    expect(fieldLabel("#/files/x")).toBe("Files");
  });

  it("keeps Retry-After for 429 and both 503 kinds", async () => {
    mockFetch(429, problem("rate-limited", 429), { "Retry-After": "42" });
    expect(await errorOf(migrate(BODY))).toMatchObject({ kind: "rate_limited", retryAfter: 42 });
    mockFetch(503, problem("llm-quota-exhausted", 503), { "Retry-After": "7200" });
    expect(await errorOf(migrate(BODY))).toMatchObject({ kind: "quota", retryAfter: 7200 });
    mockFetch(503, problem("llm-unavailable", 503), { "Retry-After": "60" });
    expect(await errorOf(migrate(BODY))).toMatchObject({ kind: "busy", retryAfter: 60 });
  });

  it("reports network failures, timeouts and invalid bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect((await errorOf(getJob("mig_1"))).kind).toBe("network");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("timed out", "TimeoutError")),
    );
    expect((await errorOf(getJob("mig_1"))).kind).toBe("timeout");
    mockFetch(200, { job_id: 1 });
    expect((await errorOf(getJob("mig_1"))).kind).toBe("invalid_response");
  });
});
