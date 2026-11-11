"use client";

import { useEffect, useSyncExternalStore } from "react";

/** Chrome's offer to install. Not in lib.dom: only Chromium has it. */
type InstallOffer = Event & { prompt: () => Promise<unknown> };

let offer: InstallOffer | null = null;
const watchers = new Set<() => void>();

function keep(next: InstallOffer | null) {
  offer = next;
  watchers.forEach((watcher) => watcher());
}

/** The browser's offer to install the app, until it is taken — null on an
 *  iPhone, where installing is Share → Add to Home Screen, and once installed. */
export function useInstallOffer(): InstallOffer | null {
  return useSyncExternalStore(
    (watcher) => {
      watchers.add(watcher);
      return () => watchers.delete(watcher);
    },
    () => offer,
    () => null,
  );
}

/** Registers the service worker ([07] § 8) and keeps the offer to install. Renders nothing. */
export function ServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    const offered = (event: Event) => {
      event.preventDefault(); // ours to show, in Settings → Notifications
      keep(event as InstallOffer);
    };
    const installed = () => keep(null);
    window.addEventListener("beforeinstallprompt", offered);
    window.addEventListener("appinstalled", installed);
    return () => {
      window.removeEventListener("beforeinstallprompt", offered);
      window.removeEventListener("appinstalled", installed);
    };
  }, []);
  return null;
}
