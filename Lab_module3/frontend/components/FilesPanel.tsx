"use client";

import { type KeyboardEvent, useId, useMemo, useState } from "react";
import { compareOptions } from "@/lib/compare";
import { lineDiff, stats } from "@/lib/diff";
import { download } from "@/lib/download";
import type { JobView, MigratedFile } from "@/lib/schemas";
import DiffView from "./DiffView";

function Tabs<T extends string>(props: {
  label: string;
  items: { id: T; text: string }[];
  selected: T;
  onSelect: (id: T) => void;
  idPrefix: string;
}) {
  const { items, selected, onSelect, idPrefix } = props;
  const move = (e: KeyboardEvent, index: number) => {
    const next = e.key === "ArrowRight" ? index + 1 : e.key === "ArrowLeft" ? index - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const item = items[(next + items.length) % items.length];
    onSelect(item.id);
    document.getElementById(`${idPrefix}-${item.id}`)?.focus();
  };
  return (
    <div role="tablist" aria-label={props.label} className="flex flex-wrap gap-1">
      {items.map((item, i) => (
        <button
          key={item.id}
          id={`${idPrefix}-${item.id}`}
          type="button"
          role="tab"
          aria-selected={item.id === selected}
          tabIndex={item.id === selected ? 0 : -1}
          onClick={() => onSelect(item.id)}
          onKeyDown={(e) => move(e, i)}
          className={`rounded-md px-3 py-1.5 text-sm ${
            item.id === selected
              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "bg-zinc-100 text-zinc-800 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-200"
          }`}
        >
          {item.text}
        </button>
      ))}
    </div>
  );
}

function CodeBlock({ content, label }: { content: string; label: string }) {
  const lines = content.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="max-h-[36rem] overflow-auto rounded-md border border-zinc-200 dark:border-zinc-700"
    >
      <table className="w-full border-collapse font-mono text-xs leading-5">
        <tbody>
          {lines.map((line, i) => (
            <tr key={i}>
              <td className="select-none px-2 text-right text-zinc-500">{i + 1}</td>
              <td className="whitespace-pre pr-4">{line}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FileView({ file, job }: { file: MigratedFile; job: JobView }) {
  const [mode, setMode] = useState<"code" | "diff">("diff");
  const [split, setSplit] = useState(true);
  const options = useMemo(() => compareOptions(file, job), [file, job]);
  const [compareId, setCompareId] = useState(options[0]?.id ?? "");
  const compare = options.find((o) => o.id === compareId) ?? options[0];
  const rows = useMemo(() => lineDiff(compare?.content ?? "", file.content), [compare, file]);
  const prefix = useId();

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Tabs
          label="View"
          idPrefix={`${prefix}-mode`}
          items={[
            { id: "code", text: "Code" },
            { id: "diff", text: "Diff" },
          ]}
          selected={mode}
          onSelect={setMode}
        />
        {mode === "diff" && options.length > 0 && (
          <label className="text-sm">
            <span className="mr-2">Compare with</span>
            <select
              value={compare?.id}
              onChange={(e) => setCompareId(e.target.value)}
              className="max-w-full rounded-md border border-zinc-300 bg-transparent px-2 py-1 dark:border-zinc-600"
            >
              {options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {mode === "diff" && (
          <label className="hidden items-center gap-1 text-sm md:flex">
            <input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} />
            Side by side
          </label>
        )}
        <span className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => navigator.clipboard?.writeText(file.content)}
            className="rounded-md border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-600"
          >
            Copy
          </button>
          <button
            type="button"
            onClick={() => download(file.path.split("/").pop() ?? file.path, file.content)}
            className="rounded-md border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-600"
          >
            Download
          </button>
        </span>
      </div>
      <p className="text-xs text-zinc-600 dark:text-zinc-400">
        Version {file.version}, written by step {file.step_id}
      </p>
      {mode === "code" ? (
        <CodeBlock content={file.content} label={`Code of ${file.path}`} />
      ) : (
        <>
          {/* Side by side only where there is room; phones always get the unified view. */}
          <div className="hidden md:block">
            <DiffView rows={rows} split={split} label={`Diff of ${file.path}`} />
          </div>
          <div className="md:hidden">
            <DiffView rows={rows} split={false} label={`Diff of ${file.path}`} />
          </div>
        </>
      )}
    </div>
  );
}

export default function FilesPanel({ job }: { job: JobView }) {
  const [selected, setSelected] = useState<string | null>(null);
  const prefix = useId();
  const files = job.migrated_files;
  const hidden = (job.history ?? []).filter((v) => v.hidden);
  const current = files.find((f) => f.path === selected) ?? files[0];

  return (
    <section aria-labelledby="files-title" className="space-y-3">
      <h2 id="files-title" className="text-lg font-semibold">
        5. Migrated files
      </h2>
      {files.length === 0 ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {job.phase === "rolled_back"
            ? "Rolled back: every generated file is hidden (history below)."
            : "No migrated files yet."}
        </p>
      ) : (
        <>
          <Tabs
            label="Migrated files"
            idPrefix={`${prefix}-file`}
            items={files.map((f) => {
              const base = compareOptions(f, job)[0]?.content ?? "";
              const counts = stats(lineDiff(base, f.content));
              return { id: f.path, text: `${f.path}  +${counts.added} −${counts.removed}` };
            })}
            selected={current.path}
            onSelect={setSelected}
          />
          <div role="tabpanel" aria-labelledby={`${prefix}-file-${current.path}`}>
            <FileView key={`${current.path}@${current.version}`} file={current} job={job} />
          </div>
        </>
      )}
      {hidden.length > 0 && (
        <details className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-700">
          <summary className="cursor-pointer font-medium">
            Version history ({hidden.length} hidden)
          </summary>
          <ul className="mt-2 space-y-1">
            {(job.history ?? []).map((v) => (
              <li key={`${v.path}-${v.version}`} className={v.hidden ? "line-through" : ""}>
                <span className="font-mono">{v.path}</span> v{v.version} (step {v.step_id})
                {v.hidden && <span className="sr-only"> hidden</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
