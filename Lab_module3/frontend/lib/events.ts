/** Live job events over Server-Sent Events. The browser's EventSource reconnects on its
 * own and sends Last-Event-ID, so the backend replays only what was missed. */
import { EVENT_TYPES, EventSchemas, type EventType, type JobEvent } from "./schemas";

export interface EventHandlers {
  onEvent: (event: JobEvent) => void;
  /** The stream closed for good (not a normal `done`): the caller should poll instead. */
  onLost: () => void;
  /** An event did not match its schema. */
  onInvalid: () => void;
}

export interface Subscription {
  close: () => void;
}

interface EventSourceCtor {
  new (url: string): EventSource;
  readonly CLOSED: number;
}

export function parseEvent(type: EventType, raw: MessageEvent): JobEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw.data);
  } catch {
    return null;
  }
  const parsed = EventSchemas[type].safeParse(data);
  if (!parsed.success) return null;
  return { id: Number(raw.lastEventId) || 0, type, data: parsed.data } as JobEvent;
}

export function subscribe(
  url: string,
  handlers: EventHandlers,
  EventSourceImpl: EventSourceCtor | undefined = globalThis.EventSource,
): Subscription {
  if (!EventSourceImpl) {
    handlers.onLost();
    return { close: () => {} };
  }
  const source = new EventSourceImpl(url);
  let finished = false;
  const close = () => {
    finished = true;
    source.close();
  };

  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (raw) => {
      const event = parseEvent(type, raw as MessageEvent);
      if (!event) {
        handlers.onInvalid();
        return;
      }
      if (event.type === "done") close(); // the server ends the stream after `done`
      handlers.onEvent(event);
    });
  }
  source.onerror = () => {
    // CONNECTING = the browser is retrying by itself; CLOSED = it gave up.
    if (!finished && source.readyState === EventSourceImpl.CLOSED) {
      finished = true;
      handlers.onLost();
    }
  };
  return { close };
}
