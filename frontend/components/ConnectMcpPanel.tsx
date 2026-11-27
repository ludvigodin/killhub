"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

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
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const config = mcpConfigJson(origin);
  const endpoint = `${origin}/mcp`;

  async function copyConfig() {
    try {
      await navigator.clipboard.writeText(config);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/60 backdrop-blur-[1px]"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 w-full max-w-md rounded-xl border border-(--line) bg-(--paper-deep) text-left shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-(--line) px-5 py-4">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="text-lg font-semibold tracking-tight text-(--ink)"
              style={{
                fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
              }}
            >
              Connect MCP
            </h2>
            <p className="mt-1 text-sm leading-snug text-(--muted)">
              Point Cursor or Claude at Killhub’s public MCP endpoint. Same Jobs
              API and admission caps as the UI — secrets stay on the control
              plane.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md px-2 py-1 text-lg leading-none text-(--muted) transition hover:bg-(--paper) hover:text-(--ink)"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <div>
            <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-(--muted)">
              Endpoint
            </p>
            <p className="truncate rounded-md border border-(--line) bg-(--paper) px-3 py-2 font-mono text-xs text-(--accent)">
              {endpoint}
            </p>
          </div>

          <div>
            <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-(--muted)">
              Config snippet
            </p>
            <pre className="overflow-x-auto rounded-md border border-(--line) bg-(--paper) px-3 py-2.5 font-mono text-[12px] leading-5 whitespace-pre text-(--ink)">
              {config}
            </pre>
          </div>
        </div>

        <div className="flex flex-col gap-3 border-t border-(--line) px-5 py-4">
          <button
            type="button"
            onClick={() => void copyConfig()}
            className="w-full rounded-md bg-(--accent) px-4 py-2.5 text-sm font-medium text-(--paper) transition hover:brightness-110"
          >
            {copied ? "Copied" : "Copy config"}
          </button>
          <p className="text-center text-xs leading-snug text-(--muted)">
            Prefer slim tools:{" "}
            <code className="font-mono text-(--ink)">create_and_wait</code>,{" "}
            <code className="font-mono text-(--ink)">get_receipt</code>,{" "}
            <code className="font-mono text-(--ink)">run_fixture</code>.
          </p>
        </div>
      </div>
    </div>,
    document.body,
  );
}
