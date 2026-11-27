"use client";

import { useState } from "react";
import {
  type AbsorptionMoment,
  type AxisVerdict,
  type ContainmentAxis,
  type ContainmentView,
  claimTone,
  parseContainment,
  VERDICT_TONE,
} from "@/lib/containment";

type ContainmentPanelProps = {
  containment: Record<string, unknown> | null | undefined;
  /** Compact = summary strip for live view; default = full axes. */
  compact?: boolean;
};

function VerdictChip({ verdict }: { verdict: AxisVerdict }) {
  const tone = VERDICT_TONE[verdict];
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-md px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {tone.label}
    </span>
  );
}

function AbsorptionBanner({ moment }: { moment: AbsorptionMoment }) {
  const ok = moment.absorbed;
  return (
    <div
      className="containment-absorb border-b border-(--line) px-3 py-5 sm:px-5"
      style={{
        background: ok
          ? "linear-gradient(135deg, var(--ok-soft) 0%, #14161a 55%)"
          : "linear-gradient(135deg, var(--warn-soft) 0%, #14161a 55%)",
      }}
    >
      <p
        className="font-mono text-[10px] uppercase tracking-[0.18em]"
        style={{ color: ok ? "var(--ok)" : "var(--warn)" }}
      >
        Containment moment
      </p>
      <p
        className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl"
        style={{
          fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          color: ok ? "var(--ok)" : "var(--warn)",
        }}
      >
        {ok ? "Sandbox absorbed an ∞ loop" : "Absorption incomplete"}
      </p>
      <p className="mt-2 max-w-2xl text-sm text-(--ink)/90">{moment.summary}</p>
      {moment.command ? (
        <pre className="mt-3 overflow-x-auto border border-(--line) bg-(--paper)/70 px-3 py-2 font-mono text-xs text-(--muted)">
          <span className="text-(--danger)">guest$ </span>
          {moment.command}
          {ok ? (
            <span className="text-(--ok)">
              {"\n"}→ killed by exec timeout · guest still answers
            </span>
          ) : null}
        </pre>
      ) : null}
    </div>
  );
}

function AxisRow({ axis }: { axis: ContainmentAxis }) {
  const [open, setOpen] = useState(axis.id === "timeout_enforcement");
  const hasProbes = axis.probes.length > 0;
  const highlight =
    axis.id === "timeout_enforcement" && axis.verdict === "pass";

  return (
    <li
      className={`border-b border-(--line) last:border-b-0 ${highlight ? "bg-(--ok-soft)/35" : ""}`}
    >
      <div className="flex items-start gap-3 px-3 py-3 sm:px-4">
        <span
          className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
          style={{
            background: VERDICT_TONE[axis.verdict].bg,
            color: VERDICT_TONE[axis.verdict].fg,
          }}
          aria-hidden
        >
          {axis.verdict === "pass"
            ? "✓"
            : axis.verdict === "fail"
              ? "!"
              : axis.verdict === "inconclusive"
                ? "?"
                : "·"}
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p
              className="text-sm font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              {axis.label}
            </p>
            <VerdictChip verdict={axis.verdict} />
          </div>
          <p className="text-xs text-(--muted)">{axis.blurb}</p>
          {axis.detail ? (
            <p className="font-mono text-[11px] text-(--muted)">
              {axis.detail}
            </p>
          ) : null}
          {hasProbes ? (
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
              className="mt-1 font-mono text-[11px] text-(--accent) underline-offset-2 hover:underline"
            >
              {open ? "Hide" : "Show"} {axis.probes.length} probe
              {axis.probes.length === 1 ? "" : "s"}
            </button>
          ) : null}
        </div>
      </div>
      {open && hasProbes ? (
        <ul className="space-y-2 border-t border-(--line) bg-(--paper)/40 px-3 py-3 sm:px-4">
          {axis.probes.map((probe) => (
            <li
              key={`${axis.id}-${probe.name}`}
              className="flex flex-wrap items-start gap-2 text-xs"
            >
              <VerdictChip verdict={probe.verdict} />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{probe.name}</p>
                {probe.detail ? (
                  <p className="mt-0.5 break-all font-mono text-[11px] text-(--muted)">
                    {probe.detail}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function UnverifiedHostTargets({ view }: { view: ContainmentView }) {
  if (!view.unverifiedHostTargets.length) return null;
  return (
    <p className="mt-1 text-xs text-(--muted)">
      Unverified host targets: {view.unverifiedHostTargets.join(", ")}
    </p>
  );
}

function ClaimHeader({ view }: { view: ContainmentView }) {
  const tone = claimTone(view.claim);
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-(--line) px-3 py-4 sm:px-4">
      <div>
        <p className="text-xs uppercase tracking-[0.14em] text-(--muted)">
          Containment matrix
        </p>
        <h2
          className="mt-1 text-lg font-semibold tracking-tight sm:text-xl"
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Isolation evidence
        </h2>
        <p className="mt-1 text-xs text-(--muted) sm:text-sm">
          {view.passed}/{view.total} axes proven
          {view.at ? ` · ${view.at}` : ""}
        </p>
        <UnverifiedHostTargets view={view} />
      </div>
      <span
        className="inline-flex items-center rounded-md px-2.5 py-1 font-mono text-xs uppercase tracking-wide"
        style={{ background: tone.bg, color: tone.fg }}
      >
        claim · {tone.label}
      </span>
    </div>
  );
}

export function ContainmentPanel({
  containment,
  compact = false,
}: ContainmentPanelProps) {
  const view = parseContainment(containment);
  if (!view) {
    return (
      <section
        aria-label="Containment evidence"
        className="border border-(--line) bg-(--paper-deep)/55 px-4 py-4"
      >
        <p className="text-sm uppercase tracking-wide text-(--muted)">
          Containment
        </p>
        <p className="mt-2 text-sm text-(--muted)">
          No containment matrix on this receipt yet.
        </p>
      </section>
    );
  }

  if (compact) {
    const tone = claimTone(view.claim);
    return (
      <section
        aria-label="Containment summary"
        className="space-y-2 border border-(--line) bg-(--paper-deep)/55 px-4 py-3"
      >
        {view.absorption?.absorbed ? (
          <p className="text-sm font-medium" style={{ color: "var(--ok)" }}>
            Absorbed ∞ loop · guest alive
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            Containment
          </p>
          <span
            className="rounded-md px-2 py-0.5 font-mono text-xs uppercase"
            style={{ background: tone.bg, color: tone.fg }}
          >
            {tone.label}
          </span>
          <ul className="flex flex-wrap gap-1.5" aria-label="Axis verdicts">
            {view.axes.map((axis) => (
              <li key={axis.id}>
                <span
                  className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px] uppercase"
                  style={{
                    background: VERDICT_TONE[axis.verdict].bg,
                    color: VERDICT_TONE[axis.verdict].fg,
                  }}
                  title={axis.label}
                >
                  {axis.verdict === "pass"
                    ? "✓"
                    : axis.verdict === "fail"
                      ? "!"
                      : "?"}{" "}
                  {axis.id.replace(/_/g, " ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <UnverifiedHostTargets view={view} />
      </section>
    );
  }

  return (
    <section
      aria-label="Containment evidence"
      className="overflow-hidden border border-(--line) bg-(--paper-deep)/55"
    >
      {view.absorption ? <AbsorptionBanner moment={view.absorption} /> : null}
      <ClaimHeader view={view} />
      <ol>
        {view.axes.map((axis) => (
          <AxisRow key={axis.id} axis={axis} />
        ))}
      </ol>
      {view.canary ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-(--line) px-3 py-3 sm:px-4">
          <p className="text-xs uppercase tracking-wide text-(--muted)">
            Canary scan
          </p>
          <span
            className="rounded-md px-2 py-0.5 font-mono text-[10px] uppercase"
            style={{
              background: view.canary.unexpected
                ? "var(--danger-soft)"
                : "var(--ok-soft)",
              color: view.canary.unexpected ? "var(--danger)" : "var(--ok)",
            }}
          >
            {view.canary.unexpected
              ? `${view.canary.hitCount} unexpected hit${view.canary.hitCount === 1 ? "" : "s"}`
              : "clean"}
          </span>
          {view.canary.status ? (
            <span className="font-mono text-[11px] text-(--muted)">
              {view.canary.status}
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
