"use client";

import { useState } from "react";
import { type Fold, fold, type Row, sideBySide } from "@/lib/diff";

const ROW_STYLE: Record<Row["kind"], string> = {
  same: "",
  add: "bg-green-50 text-green-950 dark:bg-green-950 dark:text-green-100",
  del: "bg-red-50 text-red-950 dark:bg-red-950 dark:text-red-100",
};
const MARKER: Record<Row["kind"], string> = { same: " ", add: "+", del: "−" };
const MARKER_LABEL: Record<Row["kind"], string> = { same: "", add: "added", del: "removed" };

function Cell({ row, side }: { row: Row | null; side?: "old" | "new" }) {
  if (!row) return <td colSpan={3} className="bg-zinc-50 dark:bg-zinc-900" />;
  const number = side === "old" ? row.oldNo : side === "new" ? row.newNo : null;
  return (
    <>
      {side ? (
        <td className="select-none px-2 text-right text-zinc-500">{number}</td>
      ) : (
        <>
          <td className="select-none px-2 text-right text-zinc-500">{row.oldNo}</td>
          <td className="select-none px-2 text-right text-zinc-500">{row.newNo}</td>
        </>
      )}
      <td className={`select-none px-1 ${ROW_STYLE[row.kind]}`}>
        <span aria-hidden>{MARKER[row.kind]}</span>
        {MARKER_LABEL[row.kind] && <span className="sr-only">{MARKER_LABEL[row.kind]}</span>}
      </td>
      <td className={`whitespace-pre pr-4 ${ROW_STYLE[row.kind]}`}>{row.text}</td>
    </>
  );
}

function Folded({ item, columns, onOpen }: { item: Fold; columns: number; onOpen: () => void }) {
  return (
    <tr>
      <td colSpan={columns} className="bg-zinc-100 px-2 py-0.5 dark:bg-zinc-800">
        <button
          type="button"
          onClick={onOpen}
          className="text-blue-800 underline dark:text-blue-300"
        >
          ⋯ {item.rows.length} unchanged lines
        </button>
      </td>
    </tr>
  );
}

export default function DiffView({
  rows,
  split,
  label,
}: {
  rows: Row[];
  split: boolean;
  label: string;
}) {
  const [opened, setOpened] = useState<Set<number>>(new Set());
  const items = fold(rows);
  const columns = split ? 7 : 4;

  // Expanded folds become plain rows again; consecutive rows form one segment.
  const segments: (Row[] | { fold: Fold; index: number })[] = [];
  items.forEach((item, index) => {
    if (item.kind === "fold" && !opened.has(index)) {
      segments.push({ fold: item, index });
      return;
    }
    const rowsOf = item.kind === "fold" ? item.rows : [item];
    const last = segments.at(-1);
    if (Array.isArray(last)) last.push(...rowsOf);
    else segments.push([...rowsOf]);
  });

  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="max-h-[36rem] overflow-auto rounded-md border border-zinc-200 dark:border-zinc-700"
    >
      <table className="w-full border-collapse font-mono text-xs leading-5">
        <tbody>
          {segments.map((segment, s) =>
            Array.isArray(segment) ? (
              split ? (
                sideBySide(segment).map((pair, i) => (
                  <tr key={`${s}-${i}`}>
                    <Cell row={pair.left} side="old" />
                    <td className="w-px bg-zinc-200 dark:bg-zinc-700" />
                    <Cell row={pair.right} side="new" />
                  </tr>
                ))
              ) : (
                segment.map((row, i) => (
                  <tr key={`${s}-${i}`}>
                    <Cell row={row} />
                  </tr>
                ))
              )
            ) : (
              <Folded
                key={`fold-${segment.index}`}
                item={segment.fold}
                columns={columns}
                onOpen={() => setOpened((o) => new Set(o).add(segment.index))}
              />
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}
