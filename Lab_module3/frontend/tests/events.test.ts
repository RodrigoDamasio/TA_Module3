import { describe, expect, it, vi } from "vitest";
import { subscribe } from "@/lib/events";
import { FakeEventSource } from "./fakeEventSource";

const Ctor = FakeEventSource as unknown as typeof EventSource;

function handlers() {
  return { onEvent: vi.fn(), onLost: vi.fn(), onInvalid: vi.fn() };
}

describe("subscribe", () => {
  it("parses named events with their ids and closes after done", () => {
    const h = handlers();
    subscribe("http://x/events", h, Ctor);
    const source = FakeEventSource.instances.at(-1)!;
    source.emit("phase", { phase: "planning", replan: true }, 3);
    source.emit("done", { success: true, phase: "completed" }, 9);
    expect(h.onEvent.mock.calls.map(([e]) => [e.type, e.id])).toEqual([
      ["phase", 3],
      ["done", 9],
    ]);
    expect(h.onEvent.mock.calls[0][0].data).toMatchObject({ phase: "planning" });
    expect(source.closed).toBe(true);
    source.fail(); // the server closing the stream after done is not a loss
    expect(h.onLost).not.toHaveBeenCalled();
  });

  it("rejects events that do not match their schema", () => {
    const h = handlers();
    subscribe("http://x/events", h, Ctor);
    const source = FakeEventSource.instances.at(-1)!;
    source.emit("phase", { phase: "dancing" }, 1);
    source.emit("step", "not json", 2);
    expect(h.onInvalid).toHaveBeenCalledTimes(2);
    expect(h.onEvent).not.toHaveBeenCalled();
  });

  it("lets the browser retry, and reports a loss only when it gives up", () => {
    const h = handlers();
    const sub = subscribe("http://x/events", h, Ctor);
    const source = FakeEventSource.instances.at(-1)!;
    source.fail(FakeEventSource.CONNECTING);
    expect(h.onLost).not.toHaveBeenCalled();
    source.fail(FakeEventSource.CLOSED);
    source.fail(FakeEventSource.CLOSED);
    expect(h.onLost).toHaveBeenCalledTimes(1);
    sub.close();
  });

  it("falls back at once when EventSource is not available", () => {
    const h = handlers();
    subscribe("http://x/events", h, undefined);
    expect(h.onLost).toHaveBeenCalledTimes(1);
  });
});
