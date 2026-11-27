import type { Metadata } from "next";
import { MarketingDiagrams } from "@/components/MarketingDiagrams";
import { SiteNav } from "@/components/SiteNav";
import { featuresDescription, featuresTitle } from "@/lib/seo";

export const metadata: Metadata = {
  title: featuresTitle,
  description: featuresDescription,
  alternates: {
    canonical: "/features",
  },
};

export default function FeaturesPage() {
  return (
    <main className="min-h-screen w-full">
      <div className="mx-auto flex w-full max-w-6xl flex-col px-4 pb-24 sm:px-6">
        <SiteNav />
        <header className="pb-2 pt-4 sm:pt-6">
          <p className="type-eyebrow mb-2 text-(--accent)">Features</p>
          <h1 className="type-page-title mb-2">How Killhub runs a repo</h1>
          <p className="max-w-2xl text-base leading-relaxed text-(--muted)">
            Paste a public repo. Killhub plans how to run it, runs it in a
            disposable microVM on Vultr, records what it actually did, and
            destroys the VM – leaving a receipt you can check.
          </p>
        </header>
        <MarketingDiagrams />
      </div>
    </main>
  );
}
