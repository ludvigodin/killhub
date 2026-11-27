import type { Metadata } from "next";
import { MarketingDiagrams } from "@/components/MarketingDiagrams";
import { SiteNav } from "@/components/SiteNav";

export const metadata: Metadata = {
  title: "Features",
  description:
    "Pattern A on Vultr: plan → sandboxed execution → verifiable output → destroy.",
  alternates: {
    canonical: "/features",
  },
};

export default function FeaturesPage() {
  return (
    <main className="min-h-screen w-full">
      <div className="mx-auto flex w-full max-w-5xl flex-col px-6 pb-24">
        <SiteNav />
        <header className="pb-2 pt-4 sm:pt-6">
          <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-(--accent)">
            Features
          </p>
          <h1
            className="mb-2 text-3xl font-semibold tracking-tight sm:text-4xl"
            style={{
              fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            }}
          >
            Pattern A on Vultr
          </h1>
          <p className="max-w-xl text-base leading-relaxed text-(--muted)">
            How Killhub plans, sandboxes, proves, and destroys - with a hard
            plane boundary.
          </p>
        </header>
        <MarketingDiagrams />
      </div>
    </main>
  );
}
