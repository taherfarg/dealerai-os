"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import {
  useBrand,
  useConfirmBrand,
  useDiscardBrandDraft,
  useReadBrand,
  type Brand,
  type BrandConfirmation,
} from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

const ROLES = ["primary", "secondary", "accent", "bg", "text"] as const;
type Role = (typeof ROLES)[number];
type Cta = { text: string; locale: "en" | "ar" | "fr" };

export type BrandForm = {
  colors: Record<Role, string>;
  heading: string;
  weight: string;
  body: string;
  arabic: string;
  voice: string;
  person: string;
  formality: string;
  emoji: string;
  ctas: Cta[];
  hashtagMax: string;
  photography: string;
  logoAssetId: string | null;
};

type Source = Record<string, unknown>;
const record = (value: unknown): Source => (value && typeof value === "object" ? (value as Source) : {});
const text = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));

/** The review form, filled from a draft — or from the confirmed profile, to edit it. */
export function formFrom(source: Source): BrandForm {
  const colors = record(source.colors);
  const typography = record(source.typography);
  const tone = record(source.tone);
  const ctas = Array.isArray(source.cta_styles) ? source.cta_styles : [];
  return {
    colors: Object.fromEntries(ROLES.map((role) => [role, text(colors[role])])) as Record<Role, string>,
    heading: text(record(typography.heading).family),
    weight: text(record(typography.heading).weight),
    body: text(record(typography.body).family),
    arabic: text(record(typography.arabic).family),
    voice: text(tone.voice),
    person: text(tone.person),
    formality: text(tone.formality),
    emoji: text(tone.emoji),
    ctas: ctas
      .map((c) => (typeof c === "string" ? { text: c, locale: "en" as const } : (record(c) as Cta)))
      .filter((c) => c.text),
    hashtagMax: text(record(source.hashtag_rules).max ?? 8),
    photography: text(source.photography_style),
    logoAssetId: text(source.logo_asset_id) || null,
  };
}

/** What a person confirms: only what they filled in. A primary colour is the one thing required. */
export function confirmationFrom(form: BrandForm): BrandConfirmation | null {
  if (!/^#[0-9a-f]{6}$/i.test(form.colors.primary)) return null;
  const face = (family: string, weight?: string) =>
    family.trim() ? { family: family.trim(), ...(weight ? { weight: Number(weight) } : {}) } : null;
  return {
    colors: Object.fromEntries(
      ROLES.filter((role) => form.colors[role]).map((role) => [role, form.colors[role]]),
    ) as BrandConfirmation["colors"],
    typography: {
      heading: face(form.heading, form.weight),
      body: face(form.body),
      arabic: face(form.arabic),
    },
    tone: {
      voice: form.voice || null,
      person: form.person || null,
      formality: form.formality || null,
      emoji: (form.emoji || null) as "none" | "sparse" | "frequent" | null,
    },
    cta_styles: form.ctas.filter((c) => c.text.trim()).map((c) => ({ text: c.text.trim(), locale: c.locale })),
    hashtag_rules: { max: Number(form.hashtagMax) || 0 },
    photography_style: form.photography.trim() || null,
    logo_asset_id: form.logoAssetId,
  };
}

function Swatch({ hex, label }: { hex: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <span className="border-border inline-block size-5 rounded border" style={{ background: hex }} />
      <Ltr>{hex}</Ltr>
      {label && <span className="text-muted">{label}</span>}
    </span>
  );
}

/**
 * The dealership's brand (docs/09 § T3.1): read from its own logo, posts and
 * captions into a draft, and confirmed by a person — the only way it becomes
 * what every post is written and drawn in.
 */
export function BrandSettings() {
  const t = useT();
  const brand = useBrand();
  const [editing, setEditing] = useState(false);
  if (!brand.data) return <p className="text-muted text-sm">…</p>;
  const data = brand.data;
  const reviewing = data.draft ?? (editing ? (data as unknown as Source) : null);

  return (
    <section className="max-w-2xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold">{t("settings.brand")}</h1>
        <p className="text-muted mt-1 text-sm">{t("brand.intro")}</p>
        <p className={`mt-2 text-sm ${data.confirmed ? "text-success" : "text-warning"}`}>
          {data.confirmed ? (
            <>
              {t("brand.confirmedBy")} <Auto>{data.confirmed_by ?? "—"}</Auto>
              {data.confirmed_at && (
                <>
                  {" · "}
                  <Ltr>{data.confirmed_at.slice(0, 10)}</Ltr>
                </>
              )}
            </>
          ) : (
            t("brand.notConfirmed")
          )}
        </p>
      </header>

      {reviewing ? (
        <Review
          key={data.draft_at ?? "edit"}
          source={reviewing as Source}
          isDraft={data.draft != null}
          onDone={() => setEditing(false)}
        />
      ) : (
        <>
          <Current brand={data} onEdit={() => setEditing(true)} />
          <ReadForm />
        </>
      )}
    </section>
  );
}

function Current({ brand, onEdit }: { brand: Brand; onEdit: () => void }) {
  const t = useT();
  const colors = record(brand.colors);
  const ctas = formFrom(brand as unknown as Source).ctas;
  return (
    <section className="bg-surface rounded-2xl p-4 text-sm">
      <div className="flex flex-wrap gap-3">
        {ROLES.filter((role) => colors[role]).map((role) => (
          <Swatch key={role} hex={text(colors[role])} label={t(`brand.role.${role}`)} />
        ))}
      </div>
      {ctas.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs">
          {ctas.map((cta) => (
            <li key={cta.text}>
              <span className="pill me-2">{cta.locale}</span>
              <Auto>{cta.text}</Auto>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn mt-3" onClick={onEdit}>
        {t("brand.edit")}
      </button>
    </section>
  );
}

function ReadForm() {
  const t = useT();
  const read = useReadBrand();
  const { tenant } = useParams<{ tenant: string }>();
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const logo = form.get("logo");
    read.mutate({
      logo: logo instanceof File && logo.size > 0 ? logo : null,
      posts: form.getAll("posts").filter((f): f is File => f instanceof File && f.size > 0),
      captions: String(form.get("captions") ?? ""),
    });
  };
  return (
    <section>
      <h2 className="text-sm font-semibold">{t("brand.read")}</h2>
      <p className="text-muted mt-1 text-xs">{t("brand.readHint")}</p>
      <form onSubmit={submit} className="mt-2 space-y-2 text-xs">
        <label className="block">
          <span className="text-muted">{t("brand.logo")}</span>
          <input type="file" name="logo" accept="image/png,image/jpeg,image/webp" className="field mt-1 w-full" />
        </label>
        <label className="block">
          <span className="text-muted">{t("brand.posts")}</span>
          <input type="file" name="posts" multiple accept="image/png,image/jpeg,image/webp" className="field mt-1 w-full" />
        </label>
        <label className="block">
          <span className="text-muted">{t("brand.captions")}</span>
          <textarea name="captions" rows={6} maxLength={40000} className="field mt-1 w-full" />
        </label>
        <p className="text-muted">
          {t("brand.guide")}{" "}
          <Link href={`/${tenant}/settings/knowledge`} className="underline">
            {t("settings.knowledge")}
          </Link>
        </p>
        <div className="flex items-center gap-3">
          <button type="submit" className="btn btn-primary" disabled={read.isPending}>
            {read.isPending ? t("invoice.reading") : t("brand.readButton")}
          </button>
          {read.isError && <span className="text-danger">{read.error.message}</span>}
        </div>
      </form>
    </section>
  );
}

function Review({ source, isDraft, onDone }: { source: Source; isDraft: boolean; onDone: () => void }) {
  const t = useT();
  const confirm = useConfirmBrand();
  const discard = useDiscardBrandDraft();
  const [form, setForm] = useState<BrandForm>(() => formFrom(source));
  const set = (change: Partial<BrandForm>) => setForm({ ...form, ...change });
  const palette = (Array.isArray(source.palette) ? source.palette : []).map((p) => text(record(p).hex));
  const choices = [...new Set([...palette, ...ROLES.map((r) => form.colors[r]).filter(Boolean)])];
  const warnings = Array.isArray(source.warnings) ? source.warnings.map(text) : [];
  const body = confirmationFrom(form);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (body) confirm.mutate(body, { onSuccess: onDone });
  };

  return (
    <form onSubmit={submit} className="space-y-5 text-sm">
      {isDraft && <p className="text-muted text-xs">{t("brand.draftHint")}</p>}
      {warnings.length > 0 && (
        <ul className="bg-danger-soft text-danger list-disc rounded-md p-2 ps-6 text-xs" role="alert">
          {warnings.map((w) => (
            <li key={w} dir="auto">
              {w}
            </li>
          ))}
        </ul>
      )}

      <fieldset>
        <legend className="font-medium">{t("brand.colours")}</legend>
        {palette.length > 0 && (
          <p className="mt-1 flex flex-wrap gap-3">
            {(Array.isArray(source.palette) ? source.palette : []).map((p) => (
              <Swatch key={text(record(p).hex)} hex={text(record(p).hex)} label={`${Math.round(Number(record(p).share) * 100)}%`} />
            ))}
          </p>
        )}
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-5">
          {ROLES.map((role) => (
            <label key={role} className="text-xs">
              <span className="text-muted">{t(`brand.role.${role}`)}</span>
              <select
                value={form.colors[role]}
                onChange={(event) => set({ colors: { ...form.colors, [role]: event.target.value } })}
                className="field mt-1 w-full px-2"
                dir="ltr"
              >
                <option value="">—</option>
                {choices.map((hex) => (
                  <option key={hex} value={hex}>
                    {hex}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <legend className="font-medium">{t("brand.typefaces")}</legend>
        {(
          [
            ["heading", "brand.heading"],
            ["weight", "brand.weight"],
            ["body", "brand.body"],
            ["arabic", "brand.arabic"],
          ] as const
        ).map(([field, key]) => (
          <label key={field} className="text-xs">
            <span className="text-muted">{t(key)}</span>
            <input
              value={form[field]}
              onChange={(event) => set({ [field]: event.target.value })}
              dir="ltr"
              className="field mt-1 w-full"
            />
          </label>
        ))}
      </fieldset>

      <fieldset className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <legend className="font-medium">{t("brand.voice")}</legend>
        {(
          [
            ["voice", ["confident", "warm", "playful", "premium", "straightforward", "technical"]],
            ["person", ["we", "I", "brand_name"]],
            ["formality", ["low", "medium", "high"]],
            ["emoji", ["none", "sparse", "frequent"]],
          ] as const
        ).map(([field, options]) => (
          <label key={field} className="text-xs">
            <span className="text-muted">{t(`brand.${field}`)}</span>
            <select
              value={form[field]}
              onChange={(event) => set({ [field]: event.target.value })}
              className="field mt-1 w-full px-2"
            >
              <option value="">—</option>
              {options.map((option) => (
                <option key={option} value={option}>
                  {t(`brandOption.${option}`)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </fieldset>

      <fieldset>
        <legend className="font-medium">{t("brand.ctas")}</legend>
        <p className="text-muted text-xs">{t("brand.ctasHint")}</p>
        {form.ctas.map((cta, i) => (
          <div key={i} className="mt-1 grid grid-cols-[1fr_5rem_auto] gap-2">
            <input
              value={cta.text}
              onChange={(event) =>
                set({ ctas: form.ctas.map((c, j) => (j === i ? { ...c, text: event.target.value } : c)) })
              }
              dir="auto"
              maxLength={90}
              className="field"
            />
            <select
              value={cta.locale}
              onChange={(event) =>
                set({
                  ctas: form.ctas.map((c, j) => (j === i ? { ...c, locale: event.target.value as Cta["locale"] } : c)),
                })
              }
              className="field px-2"
            >
              {(["en", "ar", "fr"] as const).map((locale) => (
                <option key={locale} value={locale}>
                  {locale}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-quiet" onClick={() => set({ ctas: form.ctas.filter((_, j) => j !== i) })}>
              {t("pricingSettings.removeStep")}
            </button>
          </div>
        ))}
        <button type="button" className="btn mt-2" onClick={() => set({ ctas: [...form.ctas, { text: "", locale: "en" }] })}>
          {t("brand.addCta")}
        </button>
      </fieldset>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[8rem_1fr]">
        <label className="text-xs">
          <span className="text-muted">{t("brand.hashtags")}</span>
          <input
            type="number"
            min={0}
            max={30}
            value={form.hashtagMax}
            onChange={(event) => set({ hashtagMax: event.target.value })}
            dir="ltr"
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("brand.photography")}</span>
          <input
            value={form.photography}
            onChange={(event) => set({ photography: event.target.value })}
            maxLength={200}
            dir="auto"
            className="field mt-1 w-full"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" className="btn btn-primary" disabled={!body || confirm.isPending}>
          {t("brand.confirm")}
        </button>
        {isDraft ? (
          <button type="button" className="btn" disabled={discard.isPending} onClick={() => discard.mutate(undefined)}>
            {t("invoice.discard")}
          </button>
        ) : (
          <button type="button" className="btn" onClick={onDone}>
            {t("invoice.discard")}
          </button>
        )}
        {!body && <span className="text-danger text-xs">{t("brand.needPrimary")}</span>}
        {confirm.isError && <span className="text-danger text-xs">{confirm.error.message}</span>}
      </div>
    </form>
  );
}
