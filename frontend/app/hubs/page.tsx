import type { Metadata } from "next";
import { HubsFeed } from "@/components/HubsFeed";
import { hubsDescription, hubsTitle } from "@/lib/seo";

export const metadata: Metadata = {
  title: hubsTitle,
  description: hubsDescription,
  alternates: {
    canonical: "/hubs",
  },
};

export default function HubsPage() {
  return (
    <main className="min-h-screen w-full">
      <HubsFeed />
    </main>
  );
}
