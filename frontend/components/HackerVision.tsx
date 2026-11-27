"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { type FrameEvent, mapEvents, stations } from "@/lib/mainframe";
import type { ProgressLogEntry } from "./ProgressLog";
import type { mountScene } from "./telemetryScene";

const control =
  "rounded border border-[#527167] px-2.5 py-1.5 text-xs hover:bg-[#28403b] disabled:opacity-40";

export function HackerVision({ entries }: { entries: ProgressLogEntry[] }) {
  const canvas = useRef<HTMLCanvasElement>(null),
    scene = useRef<ReturnType<typeof mountScene> | null>(null);
  const [pinned, setPinned] = useState<string | null>(null),
    [followCamera, setFollowCamera] = useState(true);
  const [unavailable, setUnavailable] = useState(false),
    [modelMissing, setModelMissing] = useState(false);
  const [motionOptIn, setMotionOptIn] = useState(false);
  const events = useMemo(() => mapEvents(entries), [entries]);
  const index =
    pinned === null
      ? events.length - 1
      : Math.max(
          0,
          events.findIndex((e) => e.event.id === pinned),
        );
  const selected = events[index];
  const { banks, danger } = useMemo(() => {
    const banks: Array<FrameEvent | undefined> = Array(12);
    let danger: FrameEvent | undefined;
    for (const item of events.slice(0, index + 1)) {
      banks[item.bank] = item;
      if (item.alert) danger = item;
    }
    return { banks, danger };
  }, [events, index]);
  const lastByStation = useMemo(() => {
    const latest: Array<FrameEvent | undefined> = Array(6);
    for (const e of events) latest[e.station] = e;
    return latest;
  }, [events]);
  const state = useRef({ banks, selected, danger, followCamera });
  useEffect(() => {
    state.current = { banks, selected, danger, followCamera };
    scene.current?.update(banks, selected, Boolean(danger), followCamera);
  }, [banks, selected, danger, followCamera]);
  useEffect(() => {
    let mounted = true;
    import("./telemetryScene")
      .then(({ mountScene }) => {
        if (!mounted || !canvas.current) return;
        scene.current = mountScene(
          canvas.current,
          setPinned,
          () => setFollowCamera(false),
          () => setModelMissing(true),
        );
        const v = state.current;
        scene.current.update(
          v.banks,
          v.selected,
          Boolean(v.danger),
          v.followCamera,
        );
      })
      .catch(() => {
        if (mounted) setUnavailable(true);
      });
    return () => {
      mounted = false;
      scene.current?.dispose();
      scene.current = null;
    };
  }, []);
  const select = (item: FrameEvent) => {
    setPinned(item.event.id);
    setFollowCamera(true);
  };
  return (
    <section
      aria-label="HackerVision telemetry"
      className="overflow-hidden rounded-lg border border-[#416459] bg-[#101e20] font-mono text-[#d5e8dc]"
    >
      <header className="flex items-center justify-between gap-2 border-b border-[#38544b] px-4 py-3">
        <h2 className="text-lg font-bold tracking-tight text-[#aff0c9]">
          HackerVision{" "}
          <span className="font-normal text-[#a2b9ac]">/ Mainframe</span>
        </h2>
        <span className="text-right text-xs">
          {events.length} retained events
        </span>
      </header>
      <div className="relative bg-[#142c29]">
        <canvas
          ref={canvas}
          role="img"
          tabIndex={0}
          aria-label="Mainframe cabinets. Drag to look, use W and S to fly, A and D to turn, or select a station below."
          className="block h-72 w-full touch-pan-y outline-offset-[-3px] sm:h-96"
        />
        <div className="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
          <div className="max-w-xl border-l-2 border-[#a6e9be] bg-[#071713ed] px-3 py-2">
            <p className="text-xs uppercase tracking-wider text-[#9de9b9]">
              {selected
                ? `${stations[selected.station]} / ${selected.event.type}`
                : "Waiting for telemetry"}
            </p>
            {selected && (
              <p className="mt-1 line-clamp-2 wrap-anywhere text-sm">
                {selected.event.message}
              </p>
            )}
          </div>
          {danger && (
            <button
              type="button"
              onClick={() => select(danger)}
              className="pointer-events-auto shrink-0 rounded border border-[#eea47c] bg-[#39261f] px-2 py-1 text-xs text-[#ffd3ad]"
              title={danger.alert ?? ""}
            >
              ⚠ Event {danger.event.id}
            </button>
          )}
        </div>
      </div>
      <div className="space-y-3 border-t border-[#38544b] px-4 py-3">
        {unavailable && (
          <p className="text-sm">
            3D unavailable. Use the stations and event controls below.
          </p>
        )}
        {danger && (
          <p className="text-sm text-[#ffd3ad]">
            {danger.alert} · {danger.event.message}
            {modelMissing
              ? " · Raptor model unavailable"
              : !unavailable && " · Click the aisle to guide the raptor."}
          </p>
        )}
        <fieldset
          className="grid grid-cols-3 gap-1 sm:grid-cols-6"
          aria-label="Inspect station"
        >
          {stations.map((name, i) => (
            <button
              key={name}
              type="button"
              disabled={!lastByStation[i]}
              aria-pressed={selected?.station === i}
              onClick={() => {
                const item = lastByStation[i];
                if (item) select(item);
              }}
              className="border-t-2 border-[#445d53] py-2 text-xs hover:bg-[#28403b] aria-pressed:border-[#9ce4b4] aria-pressed:bg-[#243c32] disabled:opacity-40"
            >
              {name}
            </button>
          ))}
        </fieldset>
        {events.length > 0 && (
          <fieldset
            className="flex items-center gap-0.5"
            aria-label="Recent event bus"
          >
            {events.slice(-30).map((item) => (
              <button
                key={item.event.id}
                type="button"
                title={item.event.message}
                aria-label={`Inspect event ${item.event.id}, ${item.event.type}`}
                aria-pressed={selected?.event.id === item.event.id}
                className="group flex h-6 min-w-0 flex-1 items-center"
                onClick={() => select(item)}
              >
                <span
                  className={`block h-2 w-full group-aria-pressed:h-5 ${item.alert ? "bg-[#ff936c]" : item.bank % 2 ? "bg-[#cdb58b]" : "bg-[#76ad94]"}`}
                />
              </button>
            ))}
          </fieldset>
        )}
        {selected && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className={control}
                onClick={() =>
                  setPinned(pinned === null ? selected.event.id : null)
                }
              >
                {pinned === null ? "Hold event" : "Follow latest"}
              </button>
              <input
                aria-label="Explore retained events"
                aria-valuetext={`Event ${selected.event.id}, ${selected.event.type}`}
                className="min-w-20 flex-1 accent-[#9ce4b4]"
                type="range"
                min={0}
                max={events.length - 1}
                value={index}
                onChange={(e) => select(events[Number(e.target.value)])}
              />
              <span className="text-xs">Event {selected.event.id}</span>
              {!unavailable && (
                <button
                  className={control}
                  type="button"
                  onClick={() => {
                    setFollowCamera(!followCamera);
                    canvas.current?.focus();
                  }}
                >
                  {followCamera ? "Take flight controls" : "Track station"}
                </button>
              )}
              {danger && !unavailable && !modelMissing && (
                <button
                  type="button"
                  className={control}
                  onClick={() => scene.current?.callRaptor()}
                >
                  Call raptor
                </button>
              )}
              {danger && !unavailable && !modelMissing && (
                <button
                  type="button"
                  className={`hidden motion-reduce:inline-flex ${control}`}
                  aria-pressed={motionOptIn}
                  onClick={() => {
                    scene.current?.allowRaptorMotion(!motionOptIn);
                    setMotionOptIn(!motionOptIn);
                  }}
                >
                  {motionOptIn ? "Hold raptor pose" : "Animate raptor"}
                </button>
              )}
              {!unavailable && !followCamera && (
                <button
                  type="button"
                  className={control}
                  onClick={() => scene.current?.flyForward()}
                >
                  Fly forward
                </button>
              )}
            </div>
            {!unavailable && (
              <p className="text-xs text-[#b3c9ba]">
                Drag to look · W/S to fly · A/D to turn · Select a cabinet to
                inspect
              </p>
            )}
            <p className="flex flex-wrap gap-x-3 text-xs text-[#bad1bf]">
              {typeof selected.event.telemetry?.progress === "number" && (
                <span>Progress {selected.event.telemetry.progress}%</span>
              )}
              {typeof selected.event.telemetry?.elapsed_seconds ===
                "number" && (
                <span>Waiting {selected.event.telemetry.elapsed_seconds}s</span>
              )}
              {typeof selected.event.telemetry?.attempt === "number" && (
                <span>Attempt {selected.event.telemetry.attempt}</span>
              )}
              {selected.event.kind === "heartbeat" && (
                <span>Worker heartbeat</span>
              )}
            </p>
            <details className="text-xs">
              <summary className="cursor-pointer py-1">Event evidence</summary>
              <p>
                {selected.event.timestamp} {selected.event.kind}
              </p>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap wrap-anywhere py-2">
                {JSON.stringify(selected.event.telemetry ?? {}, null, 2)}
              </pre>
            </details>
            {danger && (
              <a
                className="text-xs text-[#afc5b7] underline underline-offset-2"
                href="/hackervision/CREDITS.txt"
                target="_blank"
                rel="noreferrer"
              >
                Raptor model by pistachio
              </a>
            )}
          </>
        )}
      </div>
    </section>
  );
}
