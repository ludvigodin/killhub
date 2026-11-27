import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { DeepLinkStart } from "@/components/DeepLinkStart";
import { githubUrlFromOwnerRepo } from "@/lib/github";
import { noindexRobots } from "@/lib/seo";

export const metadata: Metadata = {
  robots: noindexRobots,
};

async function DeepLinkShell({
  params,
}: {
  params: Promise<{ owner: string; repo: string }>;
}) {
  const { owner, repo } = await params;
  if (!githubUrlFromOwnerRepo(owner, repo)) {
    notFound();
  }
  return <DeepLinkStart owner={owner} repo={repo} />;
}

export default function DeepLinkPage(props: {
  params: Promise<{ owner: string; repo: string }>;
}) {
  return (
    <main className="min-h-screen w-full">
      <Suspense
        fallback={
          <p className="px-4 py-12 font-mono text-sm text-(--muted) sm:px-6">
            Starting scan…
          </p>
        }
      >
        <DeepLinkShell params={props.params} />
      </Suspense>
    </main>
  );
}
