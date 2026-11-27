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
        <header className="pb-4 pt-4 sm:pt-6">
          <h1
            className="mb-2 text-3xl font-semibold tracking-tight sm:text-4xl"
            style={{
              fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
            }}
          >
            Pattern A execution
          </h1>
          <p className="max-w-2xl text-base leading-relaxed text-(--muted) sm:text-lg">
            Plan → sandboxed execution → verifiable output → destroy. Real work
            in a Microsandbox — not a chat that describes what it would do.
          </p>
        </header>
        <MarketingDiagrams />
      </div>
    </main>
  );
}
