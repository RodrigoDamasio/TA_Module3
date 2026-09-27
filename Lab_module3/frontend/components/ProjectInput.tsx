"use client";

import { useId, useState } from "react";
import {
  type DraftFile,
  draftFile,
  MAX_FILES,
  MAX_TOTAL_CHARS,
  type ProjectCheck,
  readUploads,
} from "@/lib/files";
import type { Framework, Sample } from "@/lib/schemas";
import FileEditor from "./FileEditor";

interface Props {
  frameworks: Framework[];
  samples: Sample[];
  pair: Framework | null;
  onPair: (pair: Framework) => void;
  files: DraftFile[];
  onFiles: (files: DraftFile[]) => void;
  requireApproval: boolean;
  onRequireApproval: (value: boolean) => void;
  check: ProjectCheck;
  locked: boolean; // a job is running or shown: input is read-only
  submitting: boolean;
  cooldown: number; // seconds until Migrate may be retried (429 / 503)
  onSubmit: () => void;
  onSample: (id: string) => void;
  onNew: () => void;
}

export default function ProjectInput(props: Props) {
  const { frameworks, pair, files, onFiles, check, locked, submitting, cooldown } = props;
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const ids = useId();
  const sources = [...new Map(frameworks.map((f) => [f.source, f])).values()];
  const targets = frameworks.filter((f) => f.source === pair?.source);
  const extensions = pair?.source_extensions ?? [];

  const choose = (source: string, target?: string) => {
    const next =
      frameworks.find((f) => f.source === source && (!target || f.target === target)) ??
      frameworks.find((f) => f.source === source);
    if (next) props.onPair(next);
  };

  const upload = async (list: FileList | null) => {
    if (!list || list.length === 0) return;
    const { files: added, refused } = await readUploads(list, extensions);
    const kept = files.filter((f) => f.path || f.content); // drop the empty placeholder
    const room = Math.max(0, MAX_FILES - kept.length);
    const notes = [];
    if (refused.length) notes.push(`Not added (wrong type): ${refused.join(", ")}.`);
    if (added.length > room) notes.push(`Only ${MAX_FILES} files are allowed.`);
    setUploadNote(notes.join(" ") || null);
    onFiles([...kept, ...added.slice(0, room)]);
  };

  const disabledReason = submitting
    ? "Starting the migration…"
    : cooldown > 0
      ? `Please wait ${cooldown} s.`
      : check.problem;

  return (
    <section aria-labelledby={`${ids}-title`} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`${ids}-title`} className="text-lg font-semibold">
          1. Your project
        </h2>
        <label className="text-sm">
          <span className="mr-2">Try a sample</span>
          <select
            value=""
            onChange={(e) => e.target.value && props.onSample(e.target.value)}
            className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 dark:border-zinc-600"
          >
            <option value="">Choose…</option>
            {props.samples.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-sm">
          Source framework
          <select
            value={pair?.source ?? ""}
            disabled={locked}
            onChange={(e) => choose(e.target.value)}
            className="mt-1 rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 dark:border-zinc-600"
          >
            {sources.map((f) => (
              <option key={f.source} value={f.source}>
                {f.source_name}
              </option>
            ))}
          </select>
        </label>
        <span aria-hidden className="pb-2">
          →
        </span>
        <label className="flex flex-col text-sm">
          Target framework
          <select
            value={pair?.target ?? ""}
            disabled={locked}
            onChange={(e) => pair && choose(pair.source, e.target.value)}
            className="mt-1 rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 dark:border-zinc-600"
          >
            {targets.map((f) => (
              <option key={f.target} value={f.target}>
                {f.target_name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {pair && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {pair.description} Accepted files: {extensions.join(", ")}.
        </p>
      )}

      <div className="space-y-3">
        {files.map((file, i) => (
          <FileEditor
            key={file.key}
            index={i}
            file={file}
            error={check.fileErrors[file.key]}
            readOnly={locked}
            onChange={(changed) => onFiles(files.map((f) => (f.key === file.key ? changed : f)))}
            onRemove={() => onFiles(files.filter((f) => f.key !== file.key))}
          />
        ))}
      </div>

      {!locked && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <button
            type="button"
            disabled={files.length >= MAX_FILES}
            onClick={() => onFiles([...files, draftFile()])}
            className="rounded-md border border-zinc-300 px-3 py-1.5 disabled:opacity-50 dark:border-zinc-600"
          >
            Add file
          </button>
          <label className="cursor-pointer rounded-md border border-zinc-300 px-3 py-1.5 focus-within:ring-2 dark:border-zinc-600">
            Upload files
            <input
              type="file"
              multiple
              accept={extensions.join(",")}
              className="sr-only"
              onChange={(e) => {
                upload(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
          <span className="text-zinc-600 dark:text-zinc-400">
            {files.length}/{MAX_FILES} files · {check.totalChars.toLocaleString("en")}/
            {MAX_TOTAL_CHARS.toLocaleString("en")} chars
          </span>
        </div>
      )}
      {uploadNote && (
        <p role="status" className="text-sm text-amber-900 dark:text-amber-200">
          {uploadNote}
        </p>
      )}

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={props.requireApproval}
          disabled={locked}
          onChange={(e) => props.onRequireApproval(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          <strong className="font-medium">Require my approval</strong> — pause after planning so I
          can approve or reject the plan.
        </span>
      </label>

      <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">
        Your code is sent to Google Gemini (free tier) to be migrated. Don&apos;t paste secrets or
        proprietary code.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        {locked ? (
          <button
            type="button"
            onClick={props.onNew}
            className="rounded-md bg-zinc-900 px-4 py-2 font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
          >
            New migration
          </button>
        ) : (
          <button
            type="button"
            onClick={props.onSubmit}
            disabled={!!disabledReason}
            aria-busy={submitting}
            aria-describedby={disabledReason ? `${ids}-reason` : undefined}
            className="rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          >
            {submitting ? "Starting…" : "Migrate"}
          </button>
        )}
        {!locked && disabledReason && (
          <span id={`${ids}-reason`} className="text-sm text-zinc-700 dark:text-zinc-300">
            {disabledReason}
          </span>
        )}
      </div>
    </section>
  );
}
