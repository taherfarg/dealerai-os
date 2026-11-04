"use client";

import { use } from "react";
import { useMe, useInvoice, useSignInvoice } from "@/lib/api/hooks";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

/**
 * The document's own words. A commercial invoice is read by customs at the
 * destination and by the buyer's bank, so it is written in English whatever
 * language the person printing it reads the app in — as Pollux's are.
 */
const DOC = {
  title: "Commercial invoice",
  draft: "Draft — not signed",
  number: "Invoice no.",
  date: "Date",
  seller: "Seller",
  buyer: "Buyer",
  consignee: "Consignee",
  trn: "TRN",
  vehicle: "Vehicle",
  vin: "VIN / chassis no.",
  colour: "Colour",
  engine: "Engine",
  fuel: "Fuel",
  transmission: "Transmission",
  mileage: "Odometer",
  stock: "Stock no.",
  condition: "Condition",
  destination: "Destination",
  port: "Port of discharge",
  method: "Shipping",
  description: "Description",
  amount: "Amount",
  total: "Total",
  signedBy: "Signed by",
  signature: "Signature",
  kinds: { vehicle: "Vehicle", fee: "Fees", freight: "Freight", duties: "Duties", other: "Other" },
  methods: { container: "Container", shared_container: "Shared container", roro: "RoRo", air: "Air freight" },
} as const;

type Doc = {
  number: string | null;
  issued_on: string;
  currency: string;
  seller: { name: string; address: string | null; phone: string | null; email: string | null; trn: string | null };
  buyer: { name: string };
  consignee: { name: string | null; address: string | null; phone: string | null };
  sale: { type: string; destination: string | null; port_of_discharge: string | null; shipping_method: string | null };
  vehicle: Record<string, string | number | null>;
  lines: { kind: string; description: string | null; amount_minor: number }[];
  total_minor: number;
};

export default function InvoicePage({ params }: { params: Promise<{ tenant: string; orderId: string }> }) {
  const { orderId } = use(params);
  const t = useT();
  const me = useMe();
  const invoice = useInvoice(orderId);
  const sign = useSignInvoice(orderId);
  if (!invoice.data) return <p className="text-muted p-6 text-sm">…</p>;

  const data = invoice.data;
  const doc = data.document as unknown as Doc;
  const money = (minor: number) => formatMoney({ amount_minor: minor, currency: doc.currency });
  const canSign = (me.data?.permissions ?? []).includes("orders.sign");
  const vehicleRows: [string, string | number | null | undefined][] = [
    [DOC.vin, doc.vehicle.vin],
    [DOC.condition, doc.vehicle.condition],
    [DOC.colour, doc.vehicle.colour],
    [DOC.engine, doc.vehicle.engine],
    [DOC.fuel, doc.vehicle.fuel],
    [DOC.transmission, doc.vehicle.transmission],
    [DOC.mileage, doc.vehicle.mileage_km != null ? `${doc.vehicle.mileage_km} km` : null],
    [DOC.stock, doc.vehicle.stock_number],
  ];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex flex-wrap items-center gap-2 print:hidden">
        <button type="button" className="btn" onClick={() => history.back()}>
          {t("invoiceDoc.back")}
        </button>
        <button type="button" className="btn" onClick={() => window.print()}>
          {t("invoiceDoc.print")}
        </button>
        {!data.signed && canSign && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={data.problems.length > 0 || sign.isPending}
            onClick={() => sign.mutate()}
          >
            {t("invoiceDoc.sign")}
          </button>
        )}
        {sign.isError && <span className="text-danger text-xs">{sign.error.message}</span>}
        {!data.signed && data.problems.length > 0 && (
          <ul className="text-danger w-full list-disc ps-5 text-xs" role="alert" dir="auto">
            {data.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        )}
      </div>

      <article lang="en" dir="ltr" className="bg-background border-border rounded-lg border p-6 text-sm print:border-0 print:p-0">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold uppercase tracking-wide">{DOC.title}</h1>
            {!data.signed && <p className="text-danger mt-1 text-xs font-medium uppercase">{DOC.draft}</p>}
          </div>
          <dl className="text-end text-xs">
            <div>
              <dt className="text-muted inline">{DOC.number} </dt>
              <dd className="inline font-medium">{doc.number ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-muted inline">{DOC.date} </dt>
              <dd className="inline">{doc.issued_on}</dd>
            </div>
          </dl>
        </header>

        <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <h2 className="text-muted text-xs uppercase">{DOC.seller}</h2>
            <p className="font-medium">{doc.seller.name}</p>
            {doc.seller.address && <p className="whitespace-pre-line">{doc.seller.address}</p>}
            {doc.seller.phone && <p>{doc.seller.phone}</p>}
            {doc.seller.email && <p>{doc.seller.email}</p>}
            {doc.seller.trn && (
              <p>
                {DOC.trn} {doc.seller.trn}
              </p>
            )}
          </div>
          <div>
            <h2 className="text-muted text-xs uppercase">{DOC.buyer}</h2>
            <p className="font-medium">{doc.buyer.name}</p>
          </div>
          {doc.consignee.name && (
            <div>
              <h2 className="text-muted text-xs uppercase">{DOC.consignee}</h2>
              <p className="font-medium">{doc.consignee.name}</p>
              {doc.consignee.address && <p className="whitespace-pre-line">{doc.consignee.address}</p>}
              {doc.consignee.phone && <p>{doc.consignee.phone}</p>}
            </div>
          )}
        </section>

        <section className="mt-6">
          <h2 className="text-muted text-xs uppercase">{DOC.vehicle}</h2>
          <p className="font-medium">{doc.lines.find((l) => l.kind === "vehicle")?.description}</p>
          <dl className="mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs sm:grid-cols-4">
            {vehicleRows
              .filter(([, value]) => value !== null && value !== undefined && value !== "")
              .map(([label, value]) => (
                <div key={label}>
                  <dt className="text-muted">{label}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
          </dl>
        </section>

        {doc.sale.type === "export" && (
          <section className="mt-4 grid grid-cols-3 gap-4 text-xs">
            <div>
              <h2 className="text-muted uppercase">{DOC.destination}</h2>
              <p>{doc.sale.destination}</p>
            </div>
            <div>
              <h2 className="text-muted uppercase">{DOC.port}</h2>
              <p>{doc.sale.port_of_discharge ?? "—"}</p>
            </div>
            <div>
              <h2 className="text-muted uppercase">{DOC.method}</h2>
              <p>{doc.sale.shipping_method ? DOC.methods[doc.sale.shipping_method as keyof typeof DOC.methods] : "—"}</p>
            </div>
          </section>
        )}

        <table className="mt-6 w-full">
          <thead>
            <tr className="border-border border-b text-xs">
              <th className="text-muted py-1 text-start font-normal uppercase">{DOC.description}</th>
              <th className="text-muted py-1 text-end font-normal uppercase">{DOC.amount}</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((line, i) => (
              <tr key={i} className="border-border border-b">
                <td className="py-1">
                  {DOC.kinds[line.kind as keyof typeof DOC.kinds]}
                  {line.description && <span className="text-muted"> — {line.description}</span>}
                </td>
                <td className="py-1 text-end">{money(line.amount_minor)}</td>
              </tr>
            ))}
            <tr>
              <td className="py-2 font-semibold">{DOC.total}</td>
              <td className="py-2 text-end font-semibold">{money(doc.total_minor)}</td>
            </tr>
          </tbody>
        </table>

        <footer className="mt-10 grid grid-cols-2 gap-6 text-xs">
          <div>
            <p className="text-muted uppercase">{DOC.signedBy}</p>
            <p className="mt-1">
              {data.signed_by ?? "—"}
              {data.signed_at && <> · {data.signed_at.slice(0, 10)}</>}
            </p>
          </div>
          <div>
            <p className="text-muted uppercase">{DOC.signature}</p>
            <div className="border-border mt-8 border-b" />
          </div>
        </footer>
      </article>
    </div>
  );
}
