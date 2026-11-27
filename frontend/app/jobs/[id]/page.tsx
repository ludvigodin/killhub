import Link from "next/link";
import { Suspense } from "react";
import { JobLiveView } from "@/components/JobLiveView";
import { KillhubLogo } from "@/components/KillhubLogo";

async function JobShell({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobLiveView key={id} jobId={id} />;
}

export default function JobPage(props: PageProps<"/jobs/[id]">) {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col px-6 py-12 sm:py-16">
      <Link
        href="/"
        className="mb-8 inline-flex items-center gap-2 text-sm text-(--muted) no-underline hover:text-(--ink)"
        aria-label="Back to Killhub"
      >
        <span aria-hidden>←</span>
        <KillhubLogo size={20} withWordmark />
      </Link>
      <h1
        className="mb-1 text-3xl font-semibold tracking-tight"
        style={{ fontFamily: "var(--font-display), ui-sans-serif, sans-serif" }}
      >
        Job
      </h1>
      <p className="mb-8 text-sm text-(--muted)">
        Live status while running. When the job finishes, the security scan
        outcome (issues found vs clean), receipt, and profile restore from
        snapshot + SSE — leave and return anytime.
      </p>
      <Suspense
        fallback={
          <p className="font-mono text-sm text-(--muted)">Loading job…</p>
        }
      >
        <JobShell params={props.params} />
      </Suspense>
    </main>
  );
}
