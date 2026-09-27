/** Line diff (jsdiff) turned into rows we render ourselves: unified or side by side,
 * with long unchanged runs folded. */
import { diffLines } from "diff";

export type RowKind = "same" | "add" | "del";

export interface Row {
  kind: RowKind;
  oldNo: number | null;
  newNo: number | null;
  text: string;
}

export interface Fold {
  kind: "fold";
  rows: Row[];
}

export interface Pair {
  left: Row | null;
  right: Row | null;
}

function splitLines(value: string): string[] {
  const lines = value.split("\n");
  if (lines.at(-1) === "") lines.pop(); // a trailing newline is not an extra line
  return lines;
}

export function lineDiff(before: string, after: string): Row[] {
  const rows: Row[] = [];
  let oldNo = 1;
  let newNo = 1;
  for (const part of diffLines(before, after)) {
    for (const text of splitLines(part.value)) {
      if (part.added) rows.push({ kind: "add", oldNo: null, newNo: newNo++, text });
      else if (part.removed) rows.push({ kind: "del", oldNo: oldNo++, newNo: null, text });
      else rows.push({ kind: "same", oldNo: oldNo++, newNo: newNo++, text });
    }
  }
  return rows;
}

export function stats(rows: Row[]): { added: number; removed: number } {
  return {
    added: rows.filter((r) => r.kind === "add").length,
    removed: rows.filter((r) => r.kind === "del").length,
  };
}

/** Unchanged runs longer than `limit` lines keep `context` lines around changes and fold
 * the rest into one expandable item. */
export function fold(rows: Row[], limit = 8, context = 3): (Row | Fold)[] {
  const out: (Row | Fold)[] = [];
  let i = 0;
  while (i < rows.length) {
    if (rows[i].kind !== "same") {
      out.push(rows[i++]);
      continue;
    }
    let j = i;
    while (j < rows.length && rows[j].kind === "same") j++;
    const run = rows.slice(i, j);
    const keepBefore = i === 0 ? 0 : context;
    const keepAfter = j === rows.length ? 0 : context;
    if (run.length > limit && run.length > keepBefore + keepAfter) {
      out.push(...run.slice(0, keepBefore));
      out.push({ kind: "fold", rows: run.slice(keepBefore, run.length - keepAfter) });
      out.push(...run.slice(run.length - keepAfter));
    } else {
      out.push(...run);
    }
    i = j;
  }
  return out;
}

/** Side by side: each run of removals is paired line by line with the additions after it. */
export function sideBySide(rows: Row[]): Pair[] {
  const pairs: Pair[] = [];
  let i = 0;
  while (i < rows.length) {
    const row = rows[i];
    if (row.kind === "same") {
      pairs.push({ left: row, right: row });
      i++;
      continue;
    }
    const dels: Row[] = [];
    const adds: Row[] = [];
    while (i < rows.length && rows[i].kind === "del") dels.push(rows[i++]);
    while (i < rows.length && rows[i].kind === "add") adds.push(rows[i++]);
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
      pairs.push({ left: dels[k] ?? null, right: adds[k] ?? null });
    }
  }
  return pairs;
}
