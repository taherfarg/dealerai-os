"use client";

import { useState, useSyncExternalStore } from "react";
import { useInstallOffer } from "@/components/ServiceWorker";
import { ApiError } from "@/lib/api/client";
import {
  useMe,
  usePushDevices,
  usePushKey,
  useRemoveDevice,
  useSubscribeDevice,
  useTestPush,
  type PushDevice,
} from "@/lib/api/hooks";
import { formatDateTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import {
  deviceName,
  isStandalone,
  needsHomeScreen,
  rememberDevice,
  rememberedDevice,
  silenceThisDevice,
  subscribeThisDevice,
  supportsPush,
  watchDevice,
} from "@/lib/push";

const BUTTON = "bg-accent min-h-11 self-start rounded-md px-4 text-sm font-medium text-black";
const QUIET = "border-border min-h-11 rounded-md border px-3 text-sm";

/** What this browser can do never changes while the page is open. */
const never = () => () => {};

/**
 * Notifications on a phone ([08] § 13): turning them on for this device,
 * the devices they reach, a test, and — where the browser offers — installing
 * the app. Everybody's: there is no permission to hold.
 */
export function NotificationSettings() {
  const t = useT();
  const locale = useLocale();
  const timezone = useMe().data?.tenant.timezone ?? "Asia/Dubai";
  const key = usePushKey();
  const devices = usePushDevices();
  const subscribe = useSubscribeDevice();
  const remove = useRemoveDevice();
  const test = useTestPush();
  const offer = useInstallOffer();
  const [trouble, setTrouble] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Only the browser knows these; undefined on the server, so the first paint matches it.
  const can = useSyncExternalStore(never, supportsPush, () => undefined);
  const homeScreen = useSyncExternalStore(
    never,
    () => needsHomeScreen(navigator.userAgent, isStandalone()),
    () => undefined,
  );
  const mine = useSyncExternalStore(watchDevice, rememberedDevice, () => null);

  const listed: PushDevice[] = devices.data ?? [];
  // On only while the server still has this device: one removed elsewhere reads
  // off here and offers the button again, rather than claiming a push it would not get.
  const on = mine !== null && listed.some((device) => device.id === mine);
  const unconfigured = key.error instanceof ApiError && key.error.problem.status === 503;

  async function turnOn() {
    if (!key.data) return;
    setTrouble(null);
    setBusy(true);
    try {
      const saved = await subscribe.mutateAsync(await subscribeThisDevice(key.data.public_key));
      rememberDevice(saved.id);
    } catch (error) {
      const denied = error instanceof Error && error.message === "denied";
      setTrouble(t(denied ? "push.blocked" : "push.failed"));
    } finally {
      setBusy(false);
    }
  }

  function forget(id: string) {
    remove.mutate(id);
    // This browser: stop it at the source too, or it would keep a subscription nobody sends to.
    if (id === mine) void silenceThisDevice();
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-lg font-semibold">{t("notifications.title")}</h1>
        <p className="text-muted text-sm">{t("push.what")}</p>
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">{t("push.thisDevice")}</h2>
        {homeScreen ? (
          <p className="text-sm">{t("push.ios")}</p>
        ) : can === false ? (
          <p className="text-muted text-sm">{t("push.unsupported")}</p>
        ) : unconfigured ? (
          <p className="text-muted text-sm">{t("push.unconfigured")}</p>
        ) : on ? (
          <p className="text-sm">{t("push.on")}</p>
        ) : (
          can && (
            <button type="button" onClick={turnOn} disabled={!key.data || busy} className={BUTTON}>
              {t("push.turnOn")}
            </button>
          )
        )}
        {trouble && (
          <p role="alert" className="text-xs text-red-600 dark:text-red-400">
            {trouble}
          </p>
        )}
        {offer && (
          <button type="button" onClick={() => void offer.prompt()} className={`${QUIET} self-start`}>
            {t("push.install")}
          </button>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">{t("push.devices")}</h2>
        {listed.length === 0 && !devices.isLoading && (
          <p className="text-muted text-sm">{t("push.noDevices")}</p>
        )}
        <ul className="flex flex-col gap-2">
          {listed.map((device) => (
            <li
              key={device.id}
              className="bg-surface border-border flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"
            >
              <span className="flex flex-col">
                <span>
                  <span dir="ltr">{deviceName(device.user_agent) || t("push.someDevice")}</span>
                  {device.id === mine && <span className="text-muted"> · {t("push.thisDevice")}</span>}
                </span>
                <span className="text-muted text-xs">
                  {device.last_success_at ? (
                    <>
                      {t("push.lastReached")}{" "}
                      <span dir="ltr">
                        {formatDateTime(device.last_success_at, timezone, locale)}
                      </span>
                    </>
                  ) : (
                    t("push.neverReached")
                  )}
                </span>
              </span>
              <button type="button" onClick={() => forget(device.id)} className={QUIET}>
                {t("push.remove")}
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending || listed.length === 0}
          className={`${QUIET} self-start disabled:opacity-50`}
        >
          {t("push.test")}
        </button>
        {test.data && (
          <p role="status" className="text-muted text-xs">
            {t("push.testSent")} {test.data.sent}
            {test.data.failed > 0 && ` · ${t("push.testFailed")} ${test.data.failed}`}
          </p>
        )}
      </section>
    </div>
  );
}
