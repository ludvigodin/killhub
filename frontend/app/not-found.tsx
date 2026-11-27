import type { Metadata } from "next";
import Link from "next/link";
import { KillhubLogo } from "@/components/KillhubLogo";

export const metadata: Metadata = {
  title: "Not found",
  description: "This path is not part of Killhub.",
};

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-6 pb-24">
      <nav className="flex items-center justify-between gap-4 py-6">
        <Link href="/" className="no-underline" aria-label="Killhub home">
          <KillhubLogo size={28} withWordmark />
        </Link>
        <Link
          href="/features"
          className="rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:text-(--ink)"
        >
          Features
        </Link>
      </nav>

      <section className="feed-hero mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center py-16 text-center sm:py-24">
        <p
          className="mb-3 font-mono text-sm tracking-widest text-(--accent) uppercase"
          aria-hidden
        >
          404
        </p>
        <h1
          className="mb-3 text-3xl font-semibold tracking-tight sm:text-4xl"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Route not found
        </h1>
        <p className="mb-8 max-w-md text-base leading-relaxed text-(--muted) sm:text-lg">
          This path isn’t part of Killhub. Head home to paste a public git URL,
          or read how Pattern A runs.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/"
            className="inline-flex min-h-11 items-center justify-center rounded-lg bg-(--accent) px-5 text-sm font-medium text-(--paper) no-underline transition hover:brightness-110"
          >
            Back to feed
          </Link>
          <Link
            href="/features"
            className="inline-flex min-h-11 items-center justify-center rounded-lg border border-(--line) bg-(--paper-deep) px-5 text-sm text-(--ink) no-underline transition hover:border-(--accent)"
          >
            Features
          </Link>
        </div>
      </section>
    </main>
  );
}
