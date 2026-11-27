import type { Metadata } from "next";
import Link from "next/link";
import { SiteNav } from "@/components/SiteNav";

export const metadata: Metadata = {
  title: "Not found",
  description: "This path is not part of Killhub.",
};

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-6 pb-24">
      <SiteNav />

      <section className="feed-hero mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center py-16 text-center sm:py-24">
        <p className="type-eyebrow mb-3 text-(--accent)" aria-hidden>
          404
        </p>
        <h1 className="type-page-title mb-3">Route not found</h1>
        <p className="mb-8 max-w-md text-base leading-relaxed text-(--muted)">
          This path isn’t part of Killhub. Head home to paste a public git URL,
          or read how Pattern A runs.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/"
            className="inline-flex min-h-11 items-center justify-center rounded-lg bg-(--accent) px-5 text-sm font-medium text-(--paper) no-underline transition hover:brightness-110"
          >
            Back
          </Link>
          <Link
            href="/hubs"
            className="inline-flex min-h-11 items-center justify-center rounded-lg border border-(--line) bg-(--paper-deep) px-5 text-sm text-(--ink) no-underline transition hover:border-(--accent)"
          >
            Hubs
          </Link>
        </div>
      </section>
    </main>
  );
}
