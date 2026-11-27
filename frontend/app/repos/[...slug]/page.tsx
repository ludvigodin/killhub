import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { RepoHistory } from "@/components/RepoHistory";
import { SiteNav } from "@/components/SiteNav";
import { githubUrlFromRepoSlug, ownerRepoFromGithubUrl } from "@/lib/github";
import { noindexRobots } from "@/lib/seo";

export const metadata: Metadata = {
  robots: noindexRobots,
};

async function RepoShell({ params }: { params: Promise<{ slug: string[] }> }) {
  const { slug } = await params;
  const githubUrl = githubUrlFromRepoSlug(slug);
  if (!githubUrl) {
    notFound();
  }
  const title = ownerRepoFromGithubUrl(githubUrl) ?? githubUrl;

  return <RepoHistory githubUrl={githubUrl} title={title} />;
}

export default function RepoPage(props: {
  params: Promise<{ slug: string[] }>;
}) {
  return (
    <main className="min-h-screen w-full">
      <div className="mx-auto flex w-full max-w-6xl flex-col px-4 pb-12 sm:px-6">
        <SiteNav />
        <Suspense
          fallback={
            <p className="font-mono text-sm text-(--muted)">Loading repo…</p>
          }
        >
          <RepoShell params={props.params} />
        </Suspense>
      </div>
    </main>
  );
}
