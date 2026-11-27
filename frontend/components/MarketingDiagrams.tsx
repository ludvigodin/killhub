import type { ReactNode } from "react";

const PIPELINE = [
  {
    label: "Plan",
    short: "Profile",
    detail: "Inspect the repo and write an executable environment profile",
  },
  {
    label: "Sandbox",
    short: "Execute",
    detail: "Clone · install · launch inside a disposable Microsandbox",
  },
  {
    label: "Prove",
    short: "Evidence",
    detail: "Readiness · install trace · isolation · cited advisories",
  },
  {
    label: "Destroy",
    short: "Receipt",
    detail: "Confirmed removal – dossier outlives the VM",
    terminal: true,
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
      <h2 className="type-display mb-2 text-2xl font-semibold tracking-tight sm:text-3xl">
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
        <p className="type-eyebrow text-(--muted)">Input</p>
        <p className="type-section-title">Public git repo</p>
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
            detail="Chat that describes work – or unsafe local runs"
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
            isGood ? "type-eyebrow text-(--ok)" : "type-eyebrow text-(--danger)"
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
            ? "type-display mb-1.5 text-base font-semibold tracking-tight text-(--ink)"
            : "type-display mb-1.5 text-base font-semibold tracking-tight text-(--muted)"
        }
      >
        {title}
      </p>
      <p className="text-sm leading-snug text-(--muted)">{detail}</p>
    </div>
  );
}

function Pipeline() {
  return (
    <figure className="pattern-loop m-0" aria-label="Pattern A loop stages">
      <ol className="pattern-loop-track m-0 list-none p-0">
        {PIPELINE.map((step, i) => {
          const terminal = "terminal" in step && step.terminal;
          return (
            <li
              key={step.label}
              className={
                terminal
                  ? "pattern-loop-step pattern-loop-step-terminal"
                  : "pattern-loop-step"
              }
              style={{ animationDelay: `${120 + i * 90}ms` }}
            >
              {i > 0 ? (
                <span className="pattern-loop-connector" aria-hidden>
                  <span className="pattern-loop-connector-line" />
                </span>
              ) : null}
              <div className="pattern-loop-card">
                <div className="pattern-loop-card-top">
                  <p className="type-mono tabular-nums text-(--accent)">
                    {String(i + 1).padStart(2, "0")}
                  </p>
                  <p className="type-eyebrow text-(--muted)">{step.short}</p>
                </div>
                <p
                  className="mb-1.5 text-base font-semibold tracking-tight text-(--ink)"
                  style={{
                    fontFamily:
                      "var(--font-display), ui-sans-serif, sans-serif",
                  }}
                >
                  {step.label}
                </p>
                <p className="text-sm leading-snug text-(--muted)">
                  {step.detail}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
      <figcaption className="pattern-loop-caption">
        <span className="pattern-loop-caption-line" aria-hidden />
        <span className="type-eyebrow text-(--muted)">
          One public URL in · real evidence out · VM gone
        </span>
        <span className="pattern-loop-caption-line" aria-hidden />
      </figcaption>
    </figure>
  );
}

function TwoPlanes() {
  return (
    <figure
      className="two-planes m-0"
      aria-label="Control plane and disposable sandbox"
    >
      <div className="two-planes-stage">
        <article className="two-planes-node two-planes-node-control">
          <header className="two-planes-node-head">
            <p className="type-eyebrow text-(--accent)">
              Plane 1 · plan & verify
            </p>
            <span className="two-planes-tag two-planes-tag-host">
              Trusted host
            </span>
          </header>
          <p className="mb-3 type-section-title">Control plane</p>
          <ul className="two-planes-list m-0 list-none space-y-2 p-0 text-sm leading-snug text-(--muted)">
            <li>
              <span className="two-planes-dot" aria-hidden />
              <span>Plans via Vultr Serverless Inference</span>
            </li>
            <li>
              <span className="two-planes-dot" aria-hidden />
              <span>
                Dispatches work · streams evidence · writes the receipt
              </span>
            </li>
            <li>
              <span className="two-planes-dot" aria-hidden />
              <span>Secrets stay here – never injected into the sandbox</span>
            </li>
          </ul>
        </article>

        <div className="two-planes-bridge" aria-hidden>
          <div className="two-planes-bridge-rail">
            <span className="two-planes-flow two-planes-flow-out" />
            <span className="two-planes-flow two-planes-flow-back" />
          </div>
          <div className="two-planes-bridge-label">
            <p className="type-eyebrow text-(--accent)">msb</p>
            <p className="text-xs leading-tight text-(--muted)">
              create · exec · destroy
            </p>
            <p className="mt-1 text-xs leading-tight text-(--muted)">
              evidence returns
            </p>
          </div>
        </div>

        <article className="two-planes-node two-planes-node-sandbox">
          <header className="two-planes-node-head">
            <p className="type-eyebrow text-(--accent)">
              Plane 2 · sandboxed execution
            </p>
            <span className="two-planes-tag two-planes-tag-ephemeral">
              Ephemeral
            </span>
          </header>
          <p className="mb-3 type-section-title">Disposable microVM</p>
          <ul className="two-planes-list m-0 list-none space-y-2 p-0 text-sm leading-snug text-(--muted)">
            <li>
              <span
                className="two-planes-dot two-planes-dot-accent"
                aria-hidden
              />
              <span>Real clone · install · launch – not described</span>
            </li>
            <li>
              <span
                className="two-planes-dot two-planes-dot-accent"
                aria-hidden
              />
              <span>Containment absorbs hostile loops / egress</span>
            </li>
            <li>
              <span
                className="two-planes-dot two-planes-dot-accent"
                aria-hidden
              />
              <span>Destroyed after the job; dossier remains</span>
            </li>
          </ul>
        </article>
      </div>

      <figcaption className="two-planes-boundary">
        <span className="two-planes-boundary-line" aria-hidden />
        <span className="type-eyebrow text-(--muted)">
          Trust boundary – untrusted code never runs as a privileged host
          process
        </span>
        <span className="two-planes-boundary-line" aria-hidden />
      </figcaption>
    </figure>
  );
}

const EVIDENCE_CLASSES = [
  {
    label: "Readiness",
    detail:
      "Starts the real app or MCP server and proves it answers – an HTTP probe or a live MCP handshake.",
  },
  {
    label: "Install activity",
    detail:
      "Every install step runs under a tracer: processes, outbound connections and DNS lookups are recorded. Sending a planted test secret out of the sandbox fails the job; writes to cron, SSH keys or shell profiles are flagged.",
  },
  {
    label: "Containment",
    detail:
      "The guest cannot reach the control plane, the host or other sandboxes, and loses all network access after install. A hostile busy-loop is killed while the guest stays alive.",
  },
  {
    label: "Dependency advisories",
    detail:
      "npm and Python lockfiles (package-lock, requirements, Pipfile, poetry.lock, uv.lock) are checked against OSV. The written summary may only cite findings that exist.",
  },
  {
    label: "MCP tool review",
    detail:
      "For Node and Python MCP servers, every tool name and description is checked for hidden instructions, invisible characters and credential-hunting prompts.",
  },
  {
    label: "Screenshots",
    detail:
      "Stills of web apps when a page renders. Useful evidence, never required to finish a job.",
  },
] as const;

const RECOVERY = [
  {
    label: "Lost sandbox",
    detail:
      "Recreated once and the run continues – never retried against a dead VM.",
  },
  {
    label: "Restart mid-job",
    detail:
      "Interrupted runs are closed with a receipt, and leftover VMs are removed.",
  },
  {
    label: "Cancel anytime",
    detail: "The VM is removed and the receipt is still written.",
  },
  {
    label: "Hard deadline",
    detail: "Anything past its expiry is reaped – no VM outlives its job.",
  },
] as const;

const DONE_EVIDENCE = [
  {
    label: "Readiness",
    detail: "Proof the app answers – or an honest “couldn’t run”",
  },
  {
    label: "Stills",
    detail: "Screenshot trail when HTTP verify captures",
  },
  {
    label: "Install trace",
    detail: "Processes, connections and leak checks",
  },
  {
    label: "Containment",
    detail: "∞ loop absorbed, then destroy",
  },
  {
    label: "Cited advisories",
    detail: "Lockfile SCA summarized with citations",
  },
] as const;

const DONE_EXCLUSIONS = [
  {
    label: "Chat-only claims",
    detail: "No “I would run…” without a sandbox",
  },
  {
    label: "Secret leakage",
    detail: "No Killhub secrets in the guest",
  },
  {
    label: "Silent exfiltration",
    detail: "A leaked test secret fails the job",
  },
  {
    label: "Leftover VM",
    detail: "No sandbox after the receipt",
  },
] as const;

function EvidenceClasses() {
  return (
    <figure
      className="evidence-ledger m-0"
      aria-label="Evidence classes Killhub collects"
    >
      <div className="evidence-ledger-sheet">
        <header className="evidence-ledger-head">
          <div>
            <p className="type-eyebrow text-(--accent)">Job evidence</p>
            <p className="mt-1 type-section-title">What Killhub tests</p>
          </div>
          <p className="evidence-ledger-stamp">
            {EVIDENCE_CLASSES.length} checks
          </p>
        </header>

        <ol className="evidence-ledger-list m-0 list-none p-0">
          {EVIDENCE_CLASSES.map((item, i) => (
            <li key={item.label} className="evidence-ledger-row">
              <span className="evidence-ledger-index type-mono tabular-nums text-(--accent)">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>
                <span className="block text-sm font-semibold tracking-tight text-(--ink)">
                  {item.label}
                </span>
                <span className="block text-sm leading-snug text-(--muted)">
                  {item.detail}
                </span>
              </span>
            </li>
          ))}
        </ol>

        <footer className="evidence-ledger-foot">
          <p className="type-eyebrow text-(--danger)">Not a pentest suite</p>
          <p className="mt-1 text-sm leading-snug text-(--muted)">
            Killhub does not weaponize CVEs or run generic app/web exploit
            packs. Containment proves isolation – it is not CVE hunting.
          </p>
        </footer>
      </div>
    </figure>
  );
}

function Recovery() {
  return (
    <ul
      className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-4"
      aria-label="How Killhub recovers from failures"
    >
      {RECOVERY.map((item) => (
        <li
          key={item.label}
          className="flex flex-col gap-1.5 rounded-lg border border-(--line) bg-(--paper-deep)/60 p-4"
        >
          <span className="text-sm font-semibold tracking-tight text-(--ink)">
            {item.label}
          </span>
          <span className="text-sm leading-snug text-(--muted)">
            {item.detail}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SecurityScope() {
  return (
    <figure
      className="done-dossier m-0"
      aria-label="What counts as done versus what does not"
    >
      <div className="done-dossier-sheet">
        <header className="done-dossier-head">
          <div>
            <p className="type-eyebrow text-(--accent)">Durable receipt</p>
            <p className="mt-1 type-section-title">Evidence outlives the VM</p>
          </div>
          <p className="done-dossier-stamp">Destroyed</p>
        </header>

        <div className="done-dossier-columns">
          <div className="done-dossier-column">
            <p className="mb-3 type-eyebrow text-(--ok)">Counts as done</p>
            <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
              {DONE_EVIDENCE.map((item) => (
                <li key={item.label} className="done-dossier-row">
                  <span
                    className="done-dossier-mark done-dossier-mark-ok"
                    aria-hidden
                  >
                    ✓
                  </span>
                  <span>
                    <span className="block text-sm font-semibold tracking-tight text-(--ink)">
                      {item.label}
                    </span>
                    <span className="block text-sm leading-snug text-(--muted)">
                      {item.detail}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="done-dossier-rule" aria-hidden />

          <div className="done-dossier-column">
            <p className="mb-3 type-eyebrow text-(--danger)">Does not count</p>
            <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
              {DONE_EXCLUSIONS.map((item) => (
                <li key={item.label} className="done-dossier-row">
                  <span
                    className="done-dossier-mark done-dossier-mark-bad"
                    aria-hidden
                  >
                    ✕
                  </span>
                  <span>
                    <span className="block text-sm font-semibold tracking-tight text-(--muted)">
                      {item.label}
                    </span>
                    <span className="block text-sm leading-snug text-(--muted)">
                      {item.detail}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </figure>
  );
}

export function MarketingDiagrams() {
  return (
    <div className="flex flex-col gap-4 pb-8 pt-6">
      <Section
        title="Why sandbox"
        support="An agent that only chats is a demo. An agent that executes safely – then destroys the environment – is a product."
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
        support="Control plane plans and verifies. Plane 2 executes. Hard boundary – untrusted code never runs as a privileged host process."
        delay={120}
      >
        <TwoPlanes />
      </Section>
      <Section
        title="What Killhub checks"
        support="Every job that gets as far as running the repo collects this evidence – plus an explicit line on what Killhub does not do."
        delay={160}
      >
        <EvidenceClasses />
      </Section>
      <Section
        title="Built to recover"
        support="Sandboxes die, hosts restart, people cancel. Each case ends with an honest result and no VM left behind."
        delay={180}
      >
        <Recovery />
      </Section>
      <Section
        title="What “done” looks like"
        support="Executed results, not descriptions: readiness, an install trace, containment, cited advisories – and a receipt that stays after the VM is gone."
        delay={220}
      >
        <SecurityScope />
      </Section>
    </div>
  );
}
