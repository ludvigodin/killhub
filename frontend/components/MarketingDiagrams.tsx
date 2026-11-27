import type { ReactNode } from "react";

const PIPELINE = [
  {
    label: "Plan",
    detail: "Agent inspects the repo and writes an executable profile",
  },
  {
    label: "Sandboxed execution",
    detail: "Clone · install · launch inside a disposable Microsandbox",
  },
  {
    label: "Verifiable output",
    detail: "Readiness evidence · screenshots · containment · receipt",
  },
  {
    label: "Destroy",
    detail: "Confirmed sandbox removal — dossier outlives the VM",
  },
] as const;

function Section({
  title,
  support,
  children,
  delay = 0,
}: {
  title: string;
  support: string;
  children: ReactNode;
  delay?: number;
}) {
  return (
    <section
      className="marketing-section border-t border-(--line) pt-14"
      style={{ animationDelay: `${delay}ms` }}
    >
      <h2
        className="mb-2 text-2xl font-semibold tracking-tight sm:text-3xl"
        style={{
          fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
        }}
      >
        {title}
      </h2>
      <p className="mb-8 max-w-2xl text-base leading-relaxed text-(--muted)">
        {support}
      </p>
      {children}
    </section>
  );
}

function ProblemFork() {
  return (
    <figure
      className="problem-fork m-0"
      aria-label="Where to run a stranger’s repo"
    >
      <div className="problem-fork-source">
        <p className="font-mono text-[11px] uppercase tracking-wider text-(--muted)">
          Input
        </p>
        <p
          className="text-lg font-semibold tracking-tight sm:text-xl"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Public git repo
        </p>
        <p className="text-sm text-(--muted)">
          Ask Killhub to bring it up. Execution must not touch your host.
        </p>
      </div>

      <div className="problem-fork-trunk" aria-hidden>
        <span className="problem-fork-dash" />
      </div>

      <div className="problem-fork-arms" aria-hidden>
        <span className="problem-fork-dash problem-fork-arms-rail" />
        <span className="problem-fork-dash problem-fork-arms-drop problem-fork-arms-drop-left" />
        <span className="problem-fork-dash problem-fork-arms-drop problem-fork-arms-drop-mid" />
        <span className="problem-fork-dash problem-fork-arms-drop problem-fork-arms-drop-right" />
      </div>

      <ul className="problem-fork-outcomes m-0 list-none p-0">
        <li>
          <Outcome
            title="Your laptop"
            detail="Chat that describes work — or unsafe local runs"
            tone="bad"
          />
        </li>
        <li>
          <Outcome
            title="Shared host"
            detail="Blast radius · secret leakage · no destroy discipline"
            tone="bad"
          />
        </li>
        <li>
          <Outcome
            title="Killhub"
            detail="Plan → sandbox → prove → destroy on Vultr"
            tone="good"
          />
        </li>
      </ul>
    </figure>
  );
}

function Outcome({
  title,
  detail,
  tone,
}: {
  title: string;
  detail: string;
  tone: "bad" | "good";
}) {
  const isGood = tone === "good";
  return (
    <div
      className={
        isGood
          ? "problem-fork-node problem-fork-node-good"
          : "problem-fork-node problem-fork-node-bad"
      }
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <span
          className={
            isGood
              ? "font-mono text-[11px] uppercase tracking-wider text-(--ok)"
              : "font-mono text-[11px] uppercase tracking-wider text-(--danger)"
          }
        >
          {isGood ? "Preferred" : "Avoid"}
        </span>
        <span
          className={
            isGood
              ? "problem-fork-mark problem-fork-mark-good"
              : "problem-fork-mark problem-fork-mark-bad"
          }
          aria-hidden
        >
          {isGood ? "✓" : "✕"}
        </span>
      </div>
      <p
        className={
          isGood
            ? "mb-1.5 text-base font-semibold tracking-tight text-(--ink)"
            : "mb-1.5 text-base font-semibold tracking-tight text-(--muted)"
        }
        style={{
          fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
        }}
      >
        {title}
      </p>
      <p className="text-sm leading-snug text-(--muted)">{detail}</p>
    </div>
  );
}

function Pipeline() {
  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {PIPELINE.map((step, i) => (
        <li
          key={step.label}
          className="relative rounded-lg border border-(--line) bg-(--paper-deep) px-3.5 py-3"
        >
          <p className="mb-1 font-mono text-[11px] tabular-nums text-(--accent)">
            {String(i + 1).padStart(2, "0")}
          </p>
          <p className="text-sm font-semibold tracking-tight text-(--ink)">
            {step.label}
          </p>
          <p className="mt-0.5 text-xs text-(--muted)">{step.detail}</p>
        </li>
      ))}
    </ol>
  );
}

function TwoPlanes() {
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
      <div className="rounded-lg border border-(--line) bg-(--paper-deep) p-5">
        <p className="mb-1 font-mono text-[11px] uppercase tracking-wider text-(--accent)">
          Plane 1 · plan & verify
        </p>
        <p
          className="mb-3 text-lg font-semibold tracking-tight"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Control plane
        </p>
        <ul className="space-y-1.5 text-sm text-(--muted)">
          <li>Plans the task via Vultr Serverless Inference</li>
          <li>Dispatches work · streams evidence · writes the receipt</li>
          <li>Secrets stay here — never injected into the sandbox</li>
        </ul>
      </div>
      <div className="flex flex-col items-center gap-1 px-2 text-center">
        <p className="font-mono text-[11px] text-(--muted)">msb</p>
        <p className="text-xs text-(--muted)">create · exec · destroy</p>
        <span className="hidden text-(--accent) lg:inline" aria-hidden>
          →
        </span>
      </div>
      <div className="rounded-lg border border-(--accent)/40 bg-(--accent-soft)/30 p-5">
        <p className="mb-1 font-mono text-[11px] uppercase tracking-wider text-(--accent)">
          Plane 2 · sandboxed execution
        </p>
        <p
          className="mb-3 text-lg font-semibold tracking-tight"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Disposable microVM
        </p>
        <ul className="space-y-1.5 text-sm text-(--muted)">
          <li>Real clone · install · launch — not described</li>
          <li>Containment absorbs hostile loops / egress</li>
          <li>Destroyed after the job; dossier remains</li>
        </ul>
      </div>
    </div>
  );
}

function SecurityScope() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="rounded-lg border border-(--ok)/35 bg-(--ok-soft)/40 p-5">
        <p className="mb-3 text-sm font-semibold text-(--ok)">Verifiable</p>
        <ul className="space-y-2 text-sm text-(--muted)">
          <li>Readiness probes with honest outcome labels</li>
          <li>Screenshot trail when HTTP verify captures stills</li>
          <li>Containment moment — ∞ loop absorbed, then destroy</li>
        </ul>
      </div>
      <div className="rounded-lg border border-(--line) bg-(--paper-deep) p-5">
        <p className="mb-3 text-sm font-semibold text-(--muted)">
          Not a chat demo
        </p>
        <ul className="space-y-2 text-sm text-(--muted)">
          <li>No “I would run…” without a sandbox</li>
          <li>No secrets in the guest</li>
          <li>No leftover VM after the receipt</li>
        </ul>
      </div>
    </div>
  );
}

export function MarketingDiagrams() {
  return (
    <div className="flex flex-col gap-4 pb-8 pt-6">
      <Section
        title="Why sandbox"
        support="An agent that only chats is a demo. An agent that executes safely — then destroys the environment — is a product."
        delay={40}
      >
        <ProblemFork />
      </Section>
      <Section
        title="Pattern A loop"
        support="Plan → sandboxed execution → verifiable output → destroy. One public URL in. Real evidence out. VM gone."
        delay={80}
      >
        <Pipeline />
      </Section>
      <Section
        title="Two planes"
        support="Control plane plans and verifies. Plane 2 executes. Hard boundary — untrusted code never runs as a privileged host process."
        delay={120}
      >
        <TwoPlanes />
      </Section>
      <Section
        title="What “done” looks like"
        support="Judges and operators see executed results: readiness, stills, containment absorption, and a durable receipt after destroy."
        delay={160}
      >
        <SecurityScope />
      </Section>
    </div>
  );
}
