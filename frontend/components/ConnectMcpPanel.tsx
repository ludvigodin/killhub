"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

type ConnectMcpPanelProps = {
  open: boolean;
  onClose: () => void;
};

type ConfigKind = "stdio" | "http";

function stdioConfigJson(): string {
  return JSON.stringify(
    {
      mcpServers: {
        killhub: {
          command: "python",
          args: ["-m", "operator_mcp"],
          cwd: "/absolute/path/to/killhub/explore",
          env: {
            KILLHUB_BASE_URL: "https://killhub.pro",
          },
        },
      },
    },
    null,
    2,
  );
}

function httpConfigJson(origin: string): string {
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
  const [kind, setKind] = useState<ConfigKind>("stdio");

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

  const config = kind === "stdio" ? stdioConfigJson() : httpConfigJson(origin);
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
            <h2 id={titleId} className="type-section-title text-(--ink)">
              Connect MCP
            </h2>
            <p className="mt-1 text-sm leading-snug text-(--muted)">
              Same Jobs API and admission caps as the UI. Secrets stay on the
              control plane. Prefer stdio in Cursor; HTTP is for remote agents.
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
          <div className="flex gap-2" role="tablist" aria-label="MCP transport">
            <button
              type="button"
              role="tab"
              aria-selected={kind === "stdio"}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                kind === "stdio"
                  ? "bg-(--accent) text-(--paper)"
                  : "border border-(--line) text-(--muted) hover:text-(--ink)"
              }`}
              onClick={() => {
                setKind("stdio");
                setCopied(false);
              }}
            >
              Stdio (recommended)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={kind === "http"}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                kind === "http"
                  ? "bg-(--accent) text-(--paper)"
                  : "border border-(--line) text-(--muted) hover:text-(--ink)"
              }`}
              onClick={() => {
                setKind("http");
                setCopied(false);
              }}
            >
              HTTP
            </button>
          </div>

          {kind === "http" ? (
            <div>
              <p className="type-eyebrow mb-1.5 text-(--muted)">Endpoint</p>
              <p className="type-mono truncate rounded-md border border-(--line) bg-(--paper) px-3 py-2 text-(--accent)">
                {endpoint}
              </p>
              <p className="mt-2 text-xs leading-snug text-(--muted)">
                DIY JSON-RPC over POST. Use{" "}
                <code className="font-mono text-(--ink)">create_job</code> +{" "}
                <code className="font-mono text-(--ink)">wait_job</code> instead
                of long{" "}
                <code className="font-mono text-(--ink)">create_and_wait</code>{" "}
                (proxy timeouts). Keep waits ≤ ~120s.
              </p>
            </div>
          ) : (
            <p className="text-xs leading-snug text-(--muted)">
              Point <code className="font-mono text-(--ink)">cwd</code> at your
              local <code className="font-mono text-(--ink)">explore/</code>{" "}
              checkout and use the venv python if needed. Most reliable in
              Cursor.
            </p>
          )}

          <div>
            <p className="type-eyebrow mb-1.5 text-(--muted)">Config snippet</p>
            <pre className="type-mono overflow-x-auto rounded-md border border-(--line) bg-(--paper) px-3 py-2.5 leading-5 whitespace-pre text-(--ink)">
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
            <code className="font-mono text-(--ink)">get_receipt</code>,{" "}
            <code className="font-mono text-(--ink)">run_fixture</code>,{" "}
            <code className="font-mono text-(--ink)">wait_job</code>.
          </p>
        </div>
      </div>
    </div>,
    document.body,
  );
}
