import type { Metadata } from "next";
import { JobFeed } from "@/components/JobFeed";
import { homeJsonLd } from "@/lib/seo";

export const metadata: Metadata = {
  alternates: {
    canonical: "/",
  },
};

export default function Home() {
  return (
    <main className="min-h-screen w-full">
      <script type="application/ld+json">{JSON.stringify(homeJsonLd)}</script>
      <JobFeed />
    </main>
  );
}
