"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { createWorkspace } from "@/lib/api/joining";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-client";
import { slugFrom } from "@/lib/slug";

/** Where a dealership might be, and what that decides: the clock its
 *  response targets and morning brief run on, and the money it quotes in. */
const PLACES = [
  { country: "AE", timezone: "Asia/Dubai", currency: "AED" },
  { country: "SA", timezone: "Asia/Riyadh", currency: "SAR" },
  { country: "QA", timezone: "Asia/Qatar", currency: "QAR" },
  { country: "KW", timezone: "Asia/Kuwait", currency: "KWD" },
  { country: "BH", timezone: "Asia/Bahrain", currency: "BHD" },
  { country: "OM", timezone: "Asia/Muscat", currency: "OMR" },
  { country: "EG", timezone: "Africa/Cairo", currency: "EGP" },
  { country: "MA", timezone: "Africa/Casablanca", currency: "MAD" },
] as const;

const LANGUAGES = ["en", "ar", "fr"] as const;
const FIELD = "field";

/** A first workspace for an owner who has none ([08] § 14). They are its
 *  owner, and the next thing they do is invite their team. */
export function CreateWorkspace() {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [country, setCountry] = useState<string>("AE");
  const [locales, setLocales] = useState<string[]>(["en", "ar"]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const regions = new Intl.DisplayNames([locale], { type: "region" });
  const place = PLACES.find((item) => item.country === country) ?? PLACES[0];

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const workspace = await createWorkspace({
        name: name.trim(),
        slug,
        country: place.country,
        timezone: place.timezone,
        currency: place.currency,
        locales,
      });
      router.push(`/${workspace.slug}/settings/team`);
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("settings.saveFailed"));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">{t("onboarding.title")}</h1>
        <p className="text-muted mt-1 text-sm">{t("onboarding.intro")}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("onboarding.name")}</span>
        <input
          required
          minLength={2}
          maxLength={120}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            if (!slugEdited) setSlug(slugFrom(event.target.value));
          }}
          className={FIELD}
        />
      </label>

      <div className="flex flex-col gap-1 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-muted">{t("onboarding.slug")}</span>
          <input
            required
            minLength={2}
            maxLength={60}
            pattern="[a-z0-9][a-z0-9\-]*"
            dir="ltr"
            aria-describedby="slug-hint"
            value={slug}
            onChange={(event) => {
              setSlug(event.target.value);
              setSlugEdited(true);
            }}
            className={FIELD}
          />
        </label>
        <span id="slug-hint" className="text-muted text-xs">
          {t("onboarding.slugHint")}
        </span>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("onboarding.country")}</span>
        <select value={country} onChange={(event) => setCountry(event.target.value)} className={FIELD}>
          {PLACES.map((item) => (
            <option key={item.country} value={item.country}>
              {regions.of(item.country)}
            </option>
          ))}
        </select>
      </label>

      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="text-muted">{t("onboarding.languages")}</legend>
        <div className="flex gap-4">
          {LANGUAGES.map((language) => (
            <label key={language} className="flex min-h-11 items-center gap-2">
              <input
                type="checkbox"
                checked={locales.includes(language)}
                onChange={(event) =>
                  setLocales((current) =>
                    event.target.checked
                      ? LANGUAGES.filter((l) => l === language || current.includes(l))
                      : current.filter((l) => l !== language),
                  )
                }
              />
              {t(`language.${language}` as MessageKey)}
            </label>
          ))}
        </div>
      </fieldset>

      {error && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy || locales.length === 0}
        className="btn btn-primary"
      >
        {t("onboarding.create")}
      </button>
    </form>
  );
}
