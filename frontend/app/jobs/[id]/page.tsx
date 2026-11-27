import type { Metadata } from "next";
import { Suspense } from "react";
import { JobLiveView } from "@/components/JobLiveView";
import { LoadingPanel } from "@/components/LoadingPanel";
import { SiteNav } from "@/components/SiteNav";
import { noindexRobots } from "@/lib/seo";

export const metadata: Metadata = {
  robots: noindexRobots,
};

async function JobShell({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobLiveView key={id} jobId={id} />;
}

export default function JobPage(props: PageProps<"/jobs/[id]">) {
  return (
    <main className="min-h-screen w-full">
      <div className="mx-auto flex w-full max-w-6xl flex-col px-6 pb-12">
        <SiteNav />
        <div className="pt-4 sm:pt-6">
          <Suspense
            fallback={
              <LoadingPanel
                label="Opening job…"
                detail="Preparing live view."
              />
            }
          >
            <JobShell params={props.params} />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
