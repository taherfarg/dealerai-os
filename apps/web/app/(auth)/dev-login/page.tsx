"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DEV_AUTH, listDevPeople, startDevSession, type DevPerson } from "@/lib/dev-auth";

export default function DevLoginPage() {
  const router = useRouter();
  const [people, setPeople] = useState<DevPerson[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (DEV_AUTH) listDevPeople().then(setPeople, (e: Error) => setError(e.message));
  }, []);

  if (!DEV_AUTH) return null;

  async function signIn(email: string) {
    try {
      const slug = await startDevSession(email);
      router.push(`/${slug}`);
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-3 p-6">
      <h1 className="text-xl font-semibold tracking-tight">Local sign-in</h1>
      <p className="text-muted text-sm">
        Seeded people only. This page does not exist in production.
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
    </main>
  );
}
