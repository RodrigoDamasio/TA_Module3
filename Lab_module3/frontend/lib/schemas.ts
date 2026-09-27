/** Zod schemas mirroring the backend (app/api/schemas.py, app/domain/job.py).
 * Every API response and every SSE event is parsed; invalid data is never rendered. */
import { z } from "zod";

export const PHASES = [
  "analysis",
  "planning",
  "awaiting_approval",
  "execution",
  "verification",
  "completed",
  "failed",
  "cancelled",
  "rolled_back",
] as const;
export const STEP_STATUSES = [
  "pending",
  "in_progress",
  "completed",
  "failed",
  "skipped",
  "rolled_back",
] as const;

export const PhaseSchema = z.enum(PHASES);
export const StepStatusSchema = z.enum(STEP_STATUSES);

export const FrameworkSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  source_name: z.string(),
  target_name: z.string(),
  source_language: z.string(),
  description: z.string(),
  source_extensions: z.array(z.string()),
});

export const StepSchema = z.object({
  id: z.number().int(),
  title: z.string(),
  description: z.string(),
  depends_on: z.array(z.number().int()),
  complexity: z.string(),
  source_files: z.array(z.string()),
  target_files: z.array(z.string()),
  status: StepStatusSchema,
  attempts: z.number().int(),
  notes: z.string().nullable(),
  error: z.string().nullable(),
});

export const PlanSchema = z.object({
  revision: z.number().int(),
  steps: z.array(StepSchema),
});

export const CheckSchema = z.object({
  name: z.string(),
  passed: z.boolean(),
  detail: z.string(),
  file: z.string().nullable(),
});

export const IssueSchema = z.object({
  severity: z.string(),
  file: z.string(),
  line: z.number().int().nullable(),
  message: z.string(),
});

export const VerificationSchema = z.object({
  passed: z.boolean(),
  checks_passed: z.boolean(),
  confidence: z.number().int(),
  verdict: z.string(),
  checks: z.array(CheckSchema),
  issues: z.array(IssueSchema),
});

export const AnalysisSchema = z.object({
  summary: z.string(),
  components: z.array(z.string()),
  dependencies: z.array(z.string()),
  patterns: z.array(z.string()),
  risks: z.array(z.string()),
});

export const FileSchema = z.object({ path: z.string(), content: z.string() });

export const MigratedFileSchema = FileSchema.extend({
  language: z.string(),
  step_id: z.number().int(),
  version: z.number().int(),
});

export const FileVersionSchema = MigratedFileSchema.extend({ hidden: z.boolean() });

export const MetaSchema = z.object({
  model: z.string(),
  prompt_version: z.string(),
  llm_calls: z.number().int(),
  cached_calls: z.number().int(),
  replans: z.number().int(),
  tokens: z.object({ input: z.number(), output: z.number() }),
  started_at: z.string(),
  updated_at: z.string(),
  finished_at: z.string().nullable(),
  approval_requested_at: z.string().nullable(),
});

export const JobViewSchema = z.object({
  job_id: z.string(),
  pair: z.string(),
  phase: PhaseSchema,
  success: z.boolean(),
  require_approval: z.boolean(),
  migrated_files: z.array(MigratedFileSchema),
  source_files: z.array(FileSchema),
  analysis: AnalysisSchema.nullable(),
  plan: PlanSchema.nullable(),
  verification: VerificationSchema.nullable(),
  errors: z.array(z.string()),
  history: z.array(FileVersionSchema).nullable().optional(),
  meta: MetaSchema,
});

export const AcceptedSchema = z.object({
  job_id: z.string(),
  phase: PhaseSchema,
  status_url: z.string(),
  events_url: z.string(),
});

export const SampleSchema = z.object({
  id: z.string(),
  title: z.string(),
  source_framework: z.string(),
  target_framework: z.string(),
  description: z.string(),
  has_result: z.boolean(),
});

export const SampleDetailSchema = SampleSchema.extend({
  files: z.array(FileSchema),
  result: JobViewSchema.nullable(),
});

export const ProblemSchema = z.object({
  type: z.string().optional(),
  title: z.string().optional(),
  status: z.number().optional(),
  detail: z.string().optional(),
  errors: z.array(z.object({ detail: z.string(), pointer: z.string() })).optional(),
});

// ---- SSE events (data payloads; the event name selects the schema) ---------------------

export const EventSchemas = {
  phase: z.looseObject({ phase: PhaseSchema }),
  analysis: AnalysisSchema,
  plan: PlanSchema,
  step: StepSchema.extend({ files: z.array(z.string()).optional() }),
  verification: VerificationSchema,
  error: z.object({ message: z.string() }),
  done: z.object({ success: z.boolean(), phase: PhaseSchema }),
} as const;

export type EventType = keyof typeof EventSchemas;
export const EVENT_TYPES = Object.keys(EventSchemas) as EventType[];

export type JobEvent = {
  [K in EventType]: { id: number; type: K; data: z.infer<(typeof EventSchemas)[K]> };
}[EventType];

export type Phase = z.infer<typeof PhaseSchema>;
export type StepStatus = z.infer<typeof StepStatusSchema>;
export type Framework = z.infer<typeof FrameworkSchema>;
export type Step = z.infer<typeof StepSchema>;
export type Plan = z.infer<typeof PlanSchema>;
export type Check = z.infer<typeof CheckSchema>;
export type Verification = z.infer<typeof VerificationSchema>;
export type SourceFile = z.infer<typeof FileSchema>;
export type MigratedFile = z.infer<typeof MigratedFileSchema>;
export type FileVersion = z.infer<typeof FileVersionSchema>;
export type JobView = z.infer<typeof JobViewSchema>;
export type Accepted = z.infer<typeof AcceptedSchema>;
export type Sample = z.infer<typeof SampleSchema>;
export type SampleDetail = z.infer<typeof SampleDetailSchema>;
