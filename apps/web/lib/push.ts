/** What the browser side of Web Push needs ([07] § 8). */

export function supportsPush(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** The server's base64url key as the bytes subscribe() takes. */
export function keyBytes(base64url: string) {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}

/** On an iPhone, notifications only work once the app is on the Home Screen (iOS 16.4+). */
export function needsHomeScreen(userAgent: string, standalone: boolean): boolean {
  return /iPhone|iPad|iPod/.test(userAgent) && !standalone;
}

export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as { standalone?: boolean }).standalone === true
  );
}

// Order matters: Edge and Chrome both say Safari, an iPhone says Mac, Android says Linux.
const BROWSERS = [
  ["Edg/", "Edge"],
  ["Firefox/", "Firefox"],
  ["CriOS/", "Chrome"],
  ["Chrome/", "Chrome"],
  ["Safari/", "Safari"],
];
const SYSTEMS = [
  ["iPhone", "iPhone"],
  ["iPad", "iPad"],
  ["Android", "Android"],
  ["Windows", "Windows"],
  ["Mac OS X", "Mac"],
  ["Linux", "Linux"],
];

/** "Chrome · Android" — enough to tell two of your own devices apart, with no
 *  word to translate. Empty when the browser said nothing we recognise. */
export function deviceName(userAgent: string | null | undefined): string {
  const named = (table: string[][]) =>
    table.find(([mark]) => (userAgent ?? "").includes(mark))?.[1];
  const browser = named(BROWSERS);
  const system = named(SYSTEMS);
  return browser && system ? `${browser} · ${system}` : "";
}

/** Ask, subscribe, and hand back what the API stores. Throws "denied" when the
 *  person — or their browser's settings — said no. */
export async function subscribeThisDevice(publicKey: string) {
  if ((await Notification.requestPermission()) !== "granted") throw new Error("denied");
  const registration = await navigator.serviceWorker.ready;
  const options = { userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) };
  const subscription = await registration.pushManager.subscribe(options).catch(async () => {
    // Subscribed once with another server's key: drop that and ask again.
    await (await registration.pushManager.getSubscription())?.unsubscribe();
    return registration.pushManager.subscribe(options);
  });
  const { endpoint, keys } = subscription.toJSON();
  if (!endpoint || !keys?.p256dh || !keys.auth) throw new Error("incomplete");
  return { endpoint, p256dh: keys.p256dh, auth: keys.auth, user_agent: navigator.userAgent };
}

/** Stop this browser receiving pushes. The push service then answers "gone"
 *  for it, and the server forgets the device. Never throws: nothing that
 *  calls this should fail over a notification. */
export async function silenceThisDevice(): Promise<void> {
  try {
    rememberDevice(null);
    if (!("serviceWorker" in navigator)) return;
    const registration = await navigator.serviceWorker.getRegistration();
    await (await registration?.pushManager?.getSubscription())?.unsubscribe();
  } catch {
    // An unsupported or half-supported browser has nothing to silence.
  }
}

const DEVICE = "push-device";
const watchers = new Set<() => void>();

/** For useSyncExternalStore: told whenever this browser's device changes. */
export function watchDevice(watcher: () => void): () => void {
  watchers.add(watcher);
  return () => watchers.delete(watcher);
}

/** Which listed device is this browser: the id the API gave it, kept here.
 *  Storage can be refused (a private window); then no device is marked. */
export function rememberedDevice(): string | null {
  try {
    return localStorage.getItem(DEVICE);
  } catch {
    return null;
  }
}

export function rememberDevice(id: string | null): void {
  try {
    if (id) localStorage.setItem(DEVICE, id);
    else localStorage.removeItem(DEVICE);
  } catch {
    // See rememberedDevice.
  }
  watchers.forEach((watcher) => watcher());
}
