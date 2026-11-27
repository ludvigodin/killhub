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
      <div className="mx-auto flex w-full max-w-5xl flex-col px-6 pb-24">
        <SiteNav />
        <header className="pb-2 pt-4 sm:pt-6">
          <p className="type-eyebrow mb-2 text-(--accent)">Features</p>
          <h1 className="type-page-title mb-2">Pattern A on Vultr</h1>
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
