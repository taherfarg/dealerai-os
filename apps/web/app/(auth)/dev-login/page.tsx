"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { safeNext } from "@/lib/auth/next";
import { DEV_AUTH, listDevPeople, startDevSession, type DevPerson } from "@/lib/dev-auth";

function DevLogin() {
  const router = useRouter();
  const params = useSearchParams();
  const [people, setPeople] = useState<DevPerson[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    if (DEV_AUTH) listDevPeople().then(setPeople, (e: Error) => setError(e.message));
  }, []);

  if (!DEV_AUTH) return null;

  async function signIn(address: string, fullName?: string) {
    try {
      const slug = await startDevSession(address, fullName);
      // A link they were on — an invitation — first; then their workspace; then
      // the root, which sends somebody with none to create one.
      router.push(params.get("next") ? safeNext(params.get("next")) : slug ? `/${slug}` : "/");
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-xl font-semibold tracking-tight">Local sign-in</h1>
      <p className="text-muted text-sm">
        Seeded people, or somebody new. This page does not exist in production.
      </p>
      {error && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}
      {people.map((person) => (
        <button
          key={person.email}
          type="button"
          onClick={() => signIn(person.email)}
          className="border-border hover:bg-surface flex justify-between rounded-md border px-3 py-2 text-start text-sm"
        >
          <span>{person.name}</span>
          <span className="text-muted">{person.role}</span>
        </button>
      ))}
      <form
        className="border-border mt-2 flex flex-col gap-2 border-t pt-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (email.trim()) signIn(email.trim(), name.trim());
        }}
      >
        <h2 className="text-sm font-semibold">Somebody new</h2>
        <input
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="layla@pollux.test"
          aria-label="Email"
          className="field"
        />
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Layla Hassan"
          aria-label="Name"
          className="field"
        />
        <button type="submit" className="btn btn-primary">
          Sign in as them
        </button>
      </form>
    </div>
  );
}

export default function DevLoginPage() {
  return (
    <Suspense>
      <DevLogin />
    </Suspense>
  );
}
