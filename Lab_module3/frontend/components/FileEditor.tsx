import { useId } from "react";
import type { DraftFile } from "@/lib/files";

interface Props {
  index: number;
  file: DraftFile;
  error?: string;
  readOnly: boolean;
  onChange: (file: DraftFile) => void;
  onRemove: () => void;
}

export default function FileEditor({ index, file, error, readOnly, onChange, onRemove }: Props) {
  const id = useId(); // stable across server render and hydration (a counter is not)
  const pathId = `${id}-path`;
  const contentId = `${id}-content`;
  const errorId = `${id}-error`;
  const lines = file.content ? file.content.split("\n").length : 0;
  return (
    <fieldset className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
      <legend className="px-1 text-sm font-medium">File {index + 1}</legend>
      <div className="flex items-center gap-2">
        <label htmlFor={pathId} className="sr-only">
          File {index + 1} path
        </label>
        <input
          id={pathId}
          value={file.path}
          readOnly={readOnly}
          placeholder="app.py"
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => onChange({ ...file, path: e.target.value })}
          className="min-w-0 flex-1 rounded-md border border-zinc-300 bg-transparent px-2 py-1 font-mono text-sm dark:border-zinc-600"
        />
        {!readOnly && (
          <button
            type="button"
            aria-label={`Remove file ${index + 1}`}
            onClick={onRemove}
            className="rounded-md px-2 py-1 text-sm text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Remove
          </button>
        )}
      </div>
      <label htmlFor={contentId} className="sr-only">
        File {index + 1} content
      </label>
      <textarea
        id={contentId}
        value={file.content}
        readOnly={readOnly}
        spellCheck={false}
        rows={8}
        placeholder="Paste the file's code here"
        onChange={(e) => onChange({ ...file, content: e.target.value })}
        className="block w-full resize-y rounded-md border border-zinc-300 bg-zinc-50 p-2 font-mono text-xs leading-5 dark:border-zinc-600 dark:bg-zinc-900"
      />
      <div className="flex flex-wrap justify-between gap-2 text-xs text-zinc-600 dark:text-zinc-400">
        <span
          id={errorId}
          className="text-red-700 dark:text-red-400"
          role={error ? "alert" : undefined}
        >
          {error}
        </span>
        <span>
          {lines} lines · {file.content.length.toLocaleString("en")} chars
        </span>
      </div>
    </fieldset>
  );
}
