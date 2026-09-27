import type { z } from "zod";
import {
  type Accepted,
  AcceptedSchema,
  type Framework,
  FrameworkSchema,
  type JobView,
  JobViewSchema,
  ProblemSchema,
  type Sample,
  type SampleDetail,
  SampleDetailSchema,
  SampleSchema,
  type SourceFile,
} from "./schemas";

export type ApiErrorKind =
  | "validation"
  | "unsupported"
  | "too_large"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "quota"
  | "busy"
  | "server"
  | "network"
  | "timeout"
  | "invalid_response";

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    message: string,
    public retryAfter?: number,
    public fieldErrors: string[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Every call returns quickly: POST /migrate answers 202 and the work streams over SSE.
const TIMEOUT_MS = 30_000;

export function apiUrl(): string {
  // Referenced directly so Next.js inlines the value at build time.
  return (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

/** "#/files/1/content" → "File 2 content"; "#/files" → "Files". */
export function fieldLabel(pointer: string): string {
  const parts = pointer.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts.length === 0) return "Request";
  if (parts[0] === "files" && parts.length >= 2) {
    const index = Number(parts[1]);
    const field = parts[2] ? ` ${parts[2]}` : "";
    return Number.isInteger(index) ? `File ${index + 1}${field}` : "Files";
  }
  const label = parts.join(" ").replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

async function toApiError(res: Response): Promise<ApiError> {
  const retryHeader = Number(res.headers.get("Retry-After"));
  const retryAfter = Number.isFinite(retryHeader) && retryHeader > 0 ? retryHeader : undefined;
  let detail: string | undefined;
  let slug = "";
  let fieldErrors: string[] = [];
  try {
    const problem = ProblemSchema.safeParse(await res.json());
    if (problem.success) {
      detail = problem.data.detail;
      slug = problem.data.type?.split("/").pop() ?? "";
      fieldErrors = (problem.data.errors ?? []).map((e) => `${fieldLabel(e.pointer)}: ${e.detail}`);
    }
  } catch {
    // Not JSON (e.g. a proxy error page) — fall back to generic messages below.
  }

  switch (res.status) {
    case 400:
      return new ApiError("validation", "The request is not valid.");
    case 422:
      if (slug === "unsupported-migration") {
        return new ApiError("unsupported", detail ?? "This migration is not supported.");
      }
      return new ApiError(
        "validation",
        detail ?? "The request is not valid.",
        undefined,
        fieldErrors,
      );
    case 413:
      return new ApiError("too_large", detail ?? "The project is too large to migrate.");
    case 404:
      return new ApiError("not_found", "This migration no longer exists.");
    case 409:
      return new ApiError(
        "conflict",
        "The migration already moved on — showing its current state.",
      );
    case 429:
      return new ApiError(
        "rate_limited",
        "You started too many migrations in a short time.",
        retryAfter,
      );
    case 503:
      if (slug === "llm-quota-exhausted") {
        return new ApiError(
          "quota",
          "Today's free AI quota is used up. The samples still work.",
          retryAfter,
        );
      }
      return new ApiError("busy", "The service is busy with other migrations.", retryAfter);
    default:
      return new ApiError("server", "Something went wrong on the server. Please try again.");
  }
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiUrl()}${path}`, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new ApiError("timeout", "The server took too long to answer. Please try again.");
    }
    throw new ApiError("network", "Can't reach the migration service. Check your connection.");
  }
  if (!res.ok) throw await toApiError(res);

  const parsed = schema.safeParse(await res.json().catch(() => undefined));
  if (!parsed.success) {
    throw new ApiError("invalid_response", "Unexpected response from the server.");
  }
  return parsed.data;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

const jobPath = (id: string) => `/migrations/${encodeURIComponent(id)}`;

export function listFrameworks(): Promise<Framework[]> {
  return request("/frameworks", FrameworkSchema.array());
}

export function listSamples(): Promise<Sample[]> {
  return request("/samples", SampleSchema.array());
}

export function getSample(id: string): Promise<SampleDetail> {
  return request(`/samples/${encodeURIComponent(id)}`, SampleDetailSchema);
}

export function migrate(body: {
  files: SourceFile[];
  source_framework: string;
  target_framework: string;
  require_approval: boolean;
}): Promise<Accepted> {
  return request("/migrate", AcceptedSchema, post(body));
}

export function getJob(id: string, includeHistory = true): Promise<JobView> {
  const query = includeHistory ? "?include_history=true" : "";
  return request(`${jobPath(id)}${query}`, JobViewSchema);
}

export function approve(id: string): Promise<JobView> {
  return request(`${jobPath(id)}/approve`, JobViewSchema, post());
}

export function reject(id: string, feedback: string | null): Promise<JobView> {
  return request(`${jobPath(id)}/reject`, JobViewSchema, post({ feedback }));
}

export function rollback(id: string): Promise<JobView> {
  return request(`${jobPath(id)}/rollback`, JobViewSchema, post());
}

export function eventsUrl(id: string): string {
  return `${apiUrl()}${jobPath(id)}/events`;
}
