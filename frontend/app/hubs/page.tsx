import type { Metadata } from "next";
import { HubsFeed } from "@/components/HubsFeed";

export const metadata: Metadata = {
  title: "Hubs",
  description:
    "All Killhub test runs — every repo planned, sandboxed, and verified.",
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
