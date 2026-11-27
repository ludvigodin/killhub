import Link from "next/link";
import { Suspense } from "react";
import { JobLiveView } from "@/components/JobLiveView";

async function JobShell({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobLiveView jobId={id} />;
}

export default function JobPage(props: PageProps<"/jobs/[id]">) {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col px-6 py-16">
      <Link href="/" className="mb-8 text-sm text-[var(--muted)]">
        ← Killhub
      </Link>
      <h1
        className="mb-2 text-3xl font-semibold tracking-tight"
        style={{ fontFamily: "var(--font-display), ui-sans-serif, sans-serif" }}
      >
        Job
      </h1>
      <Suspense
        fallback={
          <p className="font-mono text-sm text-[var(--muted)]">Loading job…</p>
        }
      >
        <JobShell params={props.params} />
      </Suspense>
    </main>
  );
}
