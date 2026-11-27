/**
 * Plane 1 job console. A short-lived operator grant stays in browser memory
 * and is sent only as a WebSocket subprotocol to the same-origin relay.
 */
"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { SectionHeader } from "./SectionHeader";

type ConsoleState = "idle" | "connecting" | "live" | "closed" | "error";

const statusText: Record<ConsoleState, string> = {
  idle: "Enter a viewing grant from your operator.",
  connecting: "Connecting to the console…",
  live: "Connected",
  closed: "Console disconnected. Use a fresh viewing grant to reconnect.",
  error: "Could not connect. Check the viewing grant and try again.",
};

export function NoVncViewer({
  jobId,
  available,
}: {
  jobId: string;
  available: boolean;
}) {
  const canvas = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [grant, setGrant] = useState("");
  const [status, setStatus] = useState<ConsoleState>("idle");

  useEffect(() => {
    if (!available || !grant) return;
    let disposed = false;
    let close: (() => void) | undefined;
    const target = canvas.current;
    if (!target) return;

    async function connect(display: HTMLDivElement) {
      try {
        const { default: RFB } = await import("@novnc/novnc");
        if (disposed) return;
        // Construct the endpoint locally. No URL or credentials from the guest
        // can direct the browser elsewhere. Plane 1 independently filters input.
        const url = new URL(
          `/api/jobs/${encodeURIComponent(jobId)}/novnc`,
          location.origin,
        );
        url.protocol = "wss:";
        const rfb = new RFB(display, url.href, {
          shared: true,
          wsProtocols: ["binary", grant],
        });
        rfb.viewOnly = true;
        rfb.scaleViewport = true;
        const onConnect = () => setStatus("live");
        const onDisconnect = () => {
          setGrant("");
          setStatus((previous) => (previous === "live" ? "closed" : "error"));
        };
        rfb.addEventListener("connect", onConnect);
        rfb.addEventListener("disconnect", onDisconnect);
        close = () => {
          rfb.removeEventListener("connect", onConnect);
          rfb.removeEventListener("disconnect", onDisconnect);
          rfb.disconnect();
          display.replaceChildren();
        };
      } catch {
        if (disposed) return;
        setGrant("");
        setStatus("error");
      }
    }

    void connect(target);
    return () => {
      disposed = true;
      close?.();
    };
  }, [available, grant, jobId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const field = input.current;
    if (!field) return;
    const value = field.value.trim();
    field.value = "";
    if (
      location.protocol !== "https:" ||
      !/^killhub-view\.[1-9][0-9]{0,9}\.[0-9]{1,12}\.[a-f0-9]{64}$/.test(value)
    ) {
      setStatus("error");
      return;
    }
    setStatus("connecting");
    setGrant(value);
  }

  return (
    <section className="space-y-3 rounded-lg border border-(--line) p-4">
      <SectionHeader title="Live console" description="View only" />
      <output className="block text-sm text-(--muted)">
        {available ? statusText[status] : "Live console unavailable."}
      </output>
      {available && !grant ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={submit}>
          <label className="grid min-w-0 gap-1 text-sm">
            Viewing grant
            {/* No field name so the browser never submits a grant as form data. */}
            <input
              ref={input}
              type="password"
              autoComplete="off"
              required
              maxLength={101}
              className="rounded-md border border-(--line) p-2"
            />
          </label>
          <button
            type="submit"
            className="rounded-md border border-(--line) px-3 py-2 text-sm"
          >
            Connect
          </button>
        </form>
      ) : null}
      <div
        ref={canvas}
        className={grant ? "aspect-video overflow-hidden rounded-md" : "hidden"}
      />
    </section>
  );
}
