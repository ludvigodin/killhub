import { notFound } from "next/navigation";
import { Suspense } from "react";
import { RepoHistory } from "@/components/RepoHistory";
import { SiteNav } from "@/components/SiteNav";
import { githubUrlFromRepoSlug, ownerRepoFromGithubUrl } from "@/lib/github";

async function RepoShell({ params }: { params: Promise<{ slug: string[] }> }) {
  const { slug } = await params;
  const githubUrl = githubUrlFromRepoSlug(slug);
  if (!githubUrl) {
    notFound();
  }
  const title = ownerRepoFromGithubUrl(githubUrl) ?? githubUrl;

  return (
    <>
      <header className="mb-10 max-w-3xl">
        <h1
          className="mb-2 text-3xl font-semibold tracking-tight sm:text-4xl"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          {title}
        </h1>
        <p className="mb-3 text-sm text-(--muted)">
          Latest run in full, with earlier runs listed below.
        </p>
        <a
          href={githubUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-(--accent) underline-offset-2 hover:underline"
        >
          {githubUrl}
        </a>
      </header>
      <RepoHistory githubUrl={githubUrl} />
    </>
  );
}

export default function RepoPage(props: {
  params: Promise<{ slug: string[] }>;
}) {
  return (
    <main className="min-h-screen w-full">
      <div className="mx-auto flex w-full max-w-5xl flex-col px-6 pb-12">
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
