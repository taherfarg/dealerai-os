"use client";

import {
  useChannels,
  useMe,
  useSyncTemplates,
  useTemplates,
  type Channel,
} from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

const QUALITY: Record<string, string> = {
  green: "bg-green-500",
  yellow: "bg-amber-500",
  red: "bg-red-500",
};

function Templates({ channel, canSync }: { channel: Channel; canSync: boolean }) {
  const t = useT();
  const templates = useTemplates(channel.id);
  const sync = useSyncTemplates(channel.id);
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold">{t("channels.templates")}</h3>
        {canSync && (
          <button
            type="button"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
            className="hover:bg-background min-h-11 rounded-md px-3 text-sm underline"
          >
            {t("channels.sync")}
          </button>
        )}
      </div>
      {(templates.data ?? []).length === 0 ? (
        <p className="text-muted text-xs">{t("channels.noTemplates")}</p>
      ) : (
        <ul className="divide-y divide-black/5 text-sm dark:divide-white/10">
          {(templates.data ?? []).map((template) => (
            <li key={template.id} className="py-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span dir="ltr">
                  {template.name} · {template.language}
                </span>
                <span className="text-muted text-xs">
                  {template.category} · {template.status}
                </span>
              </div>
              {template.rejected_reason && (
                <p className="text-xs text-red-600 dark:text-red-400">{template.rejected_reason}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The channel as it is, and the templates Meta approved (08-screens § 13).
 * Connecting Pollux's own number — Embedded Signup, the history import — is
 * S5's, and the page says so rather than showing a button that does nothing.
 */
export function ChannelSettings() {
  const t = useT();
  const me = useMe();
  const channels = useChannels();
  const canSync = (me.data?.permissions ?? []).includes("settings.channels");

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">{t("settings.channels")}</h1>
      {(channels.data ?? []).length === 0 && (
        <p className="text-muted text-sm">{t("channels.none")}</p>
      )}
      {(channels.data ?? []).map((channel) => (
        <section key={channel.id} className="bg-surface border-border rounded-lg border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium" dir="ltr">
              {channel.display_name ?? channel.handle ?? channel.platform}
            </span>
            <span className="text-muted flex items-center gap-2 text-xs">
              {channel.mode && t(`channels.mode.${channel.mode}` as MessageKey)}
              {" · "}
              {channel.status}
              {channel.quality_rating && (
                <>
                  <span
                    aria-hidden
                    className={`inline-block h-2 w-2 rounded-full ${QUALITY[channel.quality_rating] ?? ""}`}
                  />
                  {t(`channels.quality.${channel.quality_rating}` as MessageKey)}
                </>
              )}
            </span>
          </div>
          <Templates channel={channel} canSync={canSync} />
        </section>
      ))}
      <p className="text-muted text-xs">{t("channels.connectLater")}</p>
    </div>
  );
}
