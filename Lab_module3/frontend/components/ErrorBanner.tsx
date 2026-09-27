import { formatDuration } from "@/hooks/useCountdown";
import type { ApiError } from "@/lib/api";

interface Props {
  error: ApiError;
  cooldown: number; // seconds left of Retry-After
  action?: { label: string; onClick: () => void };
}

export default function ErrorBanner({ error, cooldown, action }: Props) {
  return (
    <div
      role="alert"
      className="space-y-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
    >
      <p className="font-medium">{error.message}</p>
      {error.fieldErrors.length > 0 && (
        <ul className="list-disc pl-5">
          {error.fieldErrors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {cooldown > 0 && <p>You can try again in {formatDuration(cooldown)}.</p>}
      {action && (
        <button type="button" onClick={action.onClick} className="font-medium underline">
          {action.label}
        </button>
      )}
    </div>
  );
}
