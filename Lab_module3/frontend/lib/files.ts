/** Client-side input checks — mirror the backend (app/domain/files.py, MigrationService),
 * so an invalid project never costs a request. The backend still validates everything. */
import type { SourceFile } from "./schemas";

export const MAX_FILES = 5;
export const MAX_TOTAL_CHARS = 30_000;
export const MAX_PATH_LENGTH = 120;

export interface DraftFile extends SourceFile {
  key: string; // stable React key
}

let counter = 0;
export function draftFile(path = "", content = ""): DraftFile {
  counter += 1;
  return { key: `f${counter}`, path, content };
}

export function extensionOf(path: string): string {
  const name = path.split("/").pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot) : "";
}

/** Normalizes "./a/b.py" → "a/b.py". */
export function normalizePath(path: string): string {
  return path.trim().replace(/^(\.\/)+/, "");
}

export function pathError(path: string, extensions: string[]): string | null {
  const clean = normalizePath(path);
  if (!clean) return "Enter a file path, e.g. app.py.";
  if (clean.length > MAX_PATH_LENGTH) return `Paths are limited to ${MAX_PATH_LENGTH} characters.`;
  if (clean.includes("\\")) return "Use / to separate folders.";
  if (clean.startsWith("/")) return "Use a relative path (no leading /).";
  if (clean.split("/").some((part) => part === ".." || part === "." || part === "")) {
    return "Paths must stay inside the project (no .. or empty folders).";
  }
  const ext = extensionOf(clean);
  if (!extensions.includes(ext)) return `This migration accepts ${extensions.join(", ")} files.`;
  return null;
}

export interface ProjectCheck {
  fileErrors: Record<string, string>; // key → message
  problem: string | null; // why Migrate is disabled (null = ready)
  totalChars: number;
}

export function checkProject(files: DraftFile[], extensions: string[]): ProjectCheck {
  const fileErrors: Record<string, string> = {};
  const seen = new Set<string>();
  const blank = (f: DraftFile) => !f.path.trim() && !f.content.trim();
  for (const file of files) {
    if (blank(file)) continue; // untouched: explained by `problem`, not shown as an error
    const error = pathError(file.path, extensions);
    const clean = normalizePath(file.path);
    if (error) fileErrors[file.key] = error;
    else if (seen.has(clean)) fileErrors[file.key] = "Another file already has this path.";
    else if (!file.content.trim()) fileErrors[file.key] = "Add the file's content.";
    seen.add(clean);
  }
  const totalChars = files.reduce((sum, f) => sum + f.content.length, 0);
  let problem: string | null = null;
  if (files.every(blank)) problem = "Add at least one file: its path and code.";
  else if (files.length > MAX_FILES) problem = `At most ${MAX_FILES} files per migration.`;
  else if (totalChars > MAX_TOTAL_CHARS) {
    problem = `The files have ${totalChars.toLocaleString("en")} characters; the limit is ${MAX_TOTAL_CHARS.toLocaleString("en")}.`;
  } else if (Object.keys(fileErrors).length > 0) problem = "Fix the highlighted files first.";
  else if (files.some(blank)) problem = "Fill in or remove the empty file.";
  return { fileErrors, problem, totalChars };
}

export async function readUploads(
  list: FileList | File[],
  extensions: string[],
): Promise<{ files: DraftFile[]; refused: string[] }> {
  const files: DraftFile[] = [];
  const refused: string[] = [];
  for (const file of Array.from(list)) {
    // webkitRelativePath keeps folders (e.g. routes/users.js) when a folder is chosen.
    const path = normalizePath(file.webkitRelativePath || file.name);
    if (!extensions.includes(extensionOf(path))) {
      refused.push(file.name);
      continue;
    }
    files.push(draftFile(path, await file.text()));
  }
  return { files, refused };
}
