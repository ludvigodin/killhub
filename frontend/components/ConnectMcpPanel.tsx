"use client";

import { useEffect, useId, useRef, useState } from "react";

type ConnectMcpPanelProps = {
  open: boolean;
  onClose: () => void;
};

function mcpConfigJson(origin: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        killhub: {
          url: `${origin}/mcp`,
        },
      },
    },
    null,
    2,
  );
}

export function ConnectMcpPanel({ open, onClose }: ConnectMcpPanelProps) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const [copied, setCopied] = useState(false);
  const [origin, setOrigin] = useState("https://killhub.pro");

  useEffect(() => {
    if (typeof window !== "undefined") {
      setOrigin(window.location.origin);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      setCopied(false);
      return;
    }
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const config = mcpConfigJson(origin);

  async function copyConfig() {
    try {
      await navigator.clipboard.writeText(config);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/60"
        aria-label="Close connect MCP dialog"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 w-full max-w-lg rounded-lg border border-(--line) bg-(--paper-deep) p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2
              id={titleId}
              className="text-lg font-semibold tracking-tight"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              Connect MCP
            </h2>
            <p className="mt-1 text-sm text-(--muted)">
              Point Cursor or Claude at Killhub’s public MCP endpoint. Same Jobs
              API and admission caps as the UI — secrets stay on the control
              plane.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm text-(--muted) transition hover:bg-(--paper) hover:text-(--ink)"
            aria-label="Close"
          >
            Esc
          </button>
        </div>

        <pre className="max-h-56 overflow-auto rounded-md border border-(--line) bg-(--paper) p-3 font-mono text-xs leading-relaxed text-(--ink)">
          {config}
        </pre>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void copyConfig()}
            className="rounded-md bg-(--accent) px-4 py-2 text-sm font-medium text-(--paper) transition hover:brightness-110"
          >
            {copied ? "Copied" : "Copy config"}
          </button>
          <p className="text-xs text-(--muted)">
            Prefer slim tools:{" "}
            <code className="text-(--ink)">create_and_wait</code>,{" "}
            <code className="text-(--ink)">get_receipt</code>,{" "}
            <code className="text-(--ink)">run_fixture</code>.
          </p>
        </div>
      </div>
    </div>
  );
}
