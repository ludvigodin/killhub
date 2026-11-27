import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { RepoHistory } from "@/components/RepoHistory";
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
          All Killhub runs for this repository, newest first.
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
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-12 sm:py-16">
      <Link href="/" className="mb-8 text-sm text-(--muted)">
        ← Killhub
      </Link>
      <Suspense
        fallback={
          <p className="font-mono text-sm text-(--muted)">Loading repo…</p>
        }
      >
        <RepoShell params={props.params} />
      </Suspense>
    </main>
  );
}
