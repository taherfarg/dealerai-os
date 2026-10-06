import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

// __dirname, not import.meta.url: under jsdom that is not a file: address.
const SOURCE = readFileSync(resolve(__dirname, "../public/sw.js"), "utf-8");
const ORIGIN = "https://app.test";

type Listener = (event: Record<string, unknown>) => void;

/**
 * public/sw.js is not a module, so it is run here against a pretend worker
 * scope that keeps the listeners it adds, a cache and a network.
 */
function worker({ online = true } = {}) {
  const listeners: Record<string, Listener> = {};
  const cached: string[] = [];
  const cache = { addAll: vi.fn(async (paths: string[]) => void cached.push(...paths)) };
  const caches = {
    open: vi.fn(async () => cache),
    keys: vi.fn(async () => ["dealerai-shell-v0"]),
    delete: vi.fn(async () => true),
    match: vi.fn(async (path: string) => `cached ${path}`),
  };
  const fetch = vi.fn(async () => {
    if (!online) throw new TypeError("Failed to fetch");
    return "from the network";
  });
  const scope = {
    addEventListener: (type: string, listener: Listener) => void (listeners[type] = listener),
    skipWaiting: vi.fn(async () => {}),
    registration: { showNotification: vi.fn(async () => {}) },
    clients: {
      claim: vi.fn(async () => {}),
      matchAll: vi.fn(async (): Promise<{ url: string; focus: () => void }[]> => []),
      openWindow: vi.fn(async () => {}),
    },
    location: { origin: ORIGIN },
  };
  new Function("self", "caches", "fetch", SOURCE)(scope, caches, fetch);

  /** Fire an event and wait for whatever the worker asked the browser to wait for. */
  async function fire(type: string, event: Record<string, unknown> = {}) {
    let waited: Promise<unknown> | undefined;
    let answered: Promise<unknown> | undefined;
    listeners[type]({
      ...event,
      waitUntil: (promise: Promise<unknown>) => void (waited = promise),
      respondWith: (promise: Promise<unknown>) => void (answered = promise),
    });
    await waited;
    return { answered };
  }

  return { cached, caches, scope, fire };
}

describe("the service worker", () => {
  it("keeps the offline page and an icon, and nothing a customer said", async () => {
    const { cached, fire, scope } = worker();
    await fire("install");
    expect(cached).toEqual(["/offline.html", "/icon/192"]);
    expect(scope.skipWaiting).toHaveBeenCalled();
  });

  it("drops what an older worker kept", async () => {
    const { caches, fire } = worker();
    await fire("activate");
    expect(caches.delete).toHaveBeenCalledWith("dealerai-shell-v0");
  });

  it("answers a page load with the offline page when there is no network", async () => {
    const { fire } = worker({ online: false });
    const { answered } = await fire("fetch", { request: { mode: "navigate" } });
    expect(await answered).toBe("cached /offline.html");
  });

  it("answers a page load from the network when there is one", async () => {
    const { fire } = worker();
    const { answered } = await fire("fetch", { request: { mode: "navigate" } });
    expect(await answered).toBe("from the network");
  });

  it("leaves everything else alone", async () => {
    const { fire } = worker({ online: false });
    const { answered } = await fire("fetch", {
      request: { mode: "cors", url: "http://localhost:8000/v1/conversations" },
    });
    expect(answered).toBeUndefined();
  });

  it("shows what was pushed", async () => {
    const { fire, scope } = worker();
    const said = {
      title: "A customer is waiting for you",
      body: "Omar Haddad",
      href: "/pollux-motors/inbox/42",
      tag: "assigned",
    };
    await fire("push", { data: { json: () => said } });
    expect(scope.registration.showNotification).toHaveBeenCalledWith(
      said.title,
      expect.objectContaining({ body: said.body, tag: said.tag, data: { href: said.href } }),
    );
  });

  it("opens what was tapped", async () => {
    const { fire, scope } = worker();
    const notification = { close: vi.fn(), data: { href: "/pollux-motors/inbox/42" } };
    await fire("notificationclick", { notification });
    expect(notification.close).toHaveBeenCalled();
    expect(scope.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/pollux-motors/inbox/42`);
  });

  it("goes back to a window already there rather than opening another", async () => {
    const { fire, scope } = worker();
    const open = { url: `${ORIGIN}/pollux-motors/inbox/42`, focus: vi.fn() };
    scope.clients.matchAll.mockResolvedValue([open]);
    await fire("notificationclick", {
      notification: { close: vi.fn(), data: { href: "/pollux-motors/inbox/42" } },
    });
    expect(open.focus).toHaveBeenCalled();
    expect(scope.clients.openWindow).not.toHaveBeenCalled();
  });
});
