/** Minimal EventSource double: tests push named events and errors. */
export class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = FakeEventSource.OPEN;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, ((e: MessageEvent) => void)[]>();

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
  emit(type: string, data: unknown, id: number) {
    const raw = typeof data === "string" ? data : JSON.stringify(data);
    const event = new MessageEvent(type, { data: raw, lastEventId: String(id) });
    this.listeners.get(type)?.forEach((fn) => fn(event));
  }
  fail(state = FakeEventSource.CLOSED) {
    this.readyState = state;
    this.onerror?.();
  }
}
