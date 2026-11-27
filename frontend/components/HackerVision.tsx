"use client";

import { useEffect, useRef, useState } from "react";
import type { ProgressLogEntry } from "./ProgressLog";

function signalColor(type: string) {
  if (type === "finding" || type === "error") return "#ff987b";
  if (type === "containment" || type === "screenshot") return "#deb0ff";
  if (type === "gap") return "#f7cf72";
  return "#69f8ce";
}

// Perspective projection of a corridor. Each beacon occupies one event slot.
function drawCorridor(
  canvas: HTMLCanvasElement,
  entries: ProgressLogEntry[],
  camera: number,
  selected: number,
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.clientWidth,
    h = canvas.clientHeight;
  if (!w || !h) return;
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  if (
    canvas.width !== Math.round(w * scale) ||
    canvas.height !== Math.round(h * scale)
  ) {
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
  }
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const focal = Math.min(w * 0.76, h * 1.35);
  function project(x: number, y: number, z: number) {
    return [w / 2 + (focal * x) / z, h * 0.47 - (focal * y) / z] as const;
  }
  function wire(points: number[][], color: string) {
    if (!ctx) return;
    ctx.strokeStyle = color;
    ctx.beginPath();
    for (const [i, [x, y, z]] of points.entries()) {
      const p = project(x, y, z);
      if (i === 0) ctx.moveTo(...p);
      else ctx.lineTo(...p);
    }
    ctx.stroke();
  }
  for (let x = -8; x <= 8; x++) {
    wire(
      [
        [x, -2, 1],
        [x, -2, 88],
      ],
      "#266d66",
    );
    if (x % 2 === 0)
      wire(
        [
          [x, 3, 1],
          [x, 3, 88],
        ],
        "#19414e",
      );
  }
  const travel = camera * 4;
  for (let z = 2 - (travel % 2); z < 72; z += 2) {
    if (z < 1) continue;
    wire(
      [
        [-8, 3, z],
        [-8, -2, z],
        [8, -2, z],
        [8, 3, z],
      ],
      "#225752",
    );
    wire(
      [
        [-8, 3, z],
        [8, 3, z],
      ],
      "#193945",
    );
  }
  // Look back along the stream: older events recede toward the vanishing point.
  for (
    let i = Math.max(0, Math.ceil(camera - 17));
    i <= Math.min(entries.length - 1, Math.ceil(camera));
    i++
  ) {
    const event = entries[i];
    const z = 7 + (camera - i) * 4;
    if (z < 1) continue;
    const x = i % 2 ? 2.1 : -2.1;
    const color = signalColor(event.type);
    const y = 0.1 + (i % 3) * 0.34;
    const r = 0.53;
    const rim = [
      [x - r, y, z],
      [x, y, z - r],
      [x + r, y, z],
      [x, y, z + r],
      [x - r, y, z],
    ];
    ctx.lineWidth = i === selected ? 2 : 1;
    wire(
      [
        [x, -2, z],
        [x, y - r, z],
      ],
      color,
    );
    wire(rim, color);
    for (const point of rim.slice(0, 4))
      wire([[x, y + r, z], point, [x, y - r, z]], color);
    if (i === selected) {
      const [px, py] = project(x, y + r, z);
      ctx.fillStyle = color;
      ctx.font = "bold 12px ui-monospace, monospace";
      ctx.textAlign = "center";
      ctx.fillText(event.type.toUpperCase(), px, py - 12);
    }
  }
}

export function HackerVision({ entries }: { entries: ProgressLogEntry[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const position = useRef<number | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const index =
    pinned === null
      ? entries.length - 1
      : Math.max(
          0,
          entries.findIndex((e) => e.id === pinned),
        );
  const event = entries[index];

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    const start = performance.now();
    const from = position.current ?? index;
    function paint(now: number) {
      if (!el) return;
      const t = motion.matches ? 1 : Math.min(1, (now - start) / 380);
      position.current = from + (index - from) * (1 - (1 - t) ** 3);
      drawCorridor(el, entries, position.current, index);
      if (t < 1 && from !== index) frame = requestAnimationFrame(paint);
    }
    paint(start);
    const resize = new ResizeObserver(() =>
      drawCorridor(el, entries, position.current ?? index, index),
    );
    resize.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
    };
  }, [entries, index]);

  return (
    <section
      aria-label="HackerVision telemetry"
      className="overflow-hidden rounded-lg border border-[#32665d] bg-[#07151d] font-mono text-[#bce7dc]"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[#264740] px-5 py-3">
        <h2 className="text-lg font-bold tracking-tight text-[#80ffdb]">
          HackerVision
        </h2>
        <span className="text-xs">{entries.length} retained events</span>
      </header>
      <canvas
        ref={canvas}
        role="img"
        aria-label="Perspective grid with one beacon per visible event"
        className="block h-64 w-full bg-[radial-gradient(ellipse_at_50%_47%,#21404e,#0b1928_48%,#050b13_95%)] sm:h-80"
      />
      <div className="space-y-3 border-t border-[#264740] p-5">
        {event ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-3 text-xs">
              <strong
                className="uppercase"
                style={{ color: signalColor(event.type) }}
              >
                {event.type}
              </strong>
              <span>Event {event.id}</span>
              {event.timestamp && (
                <time dateTime={event.timestamp}>{event.timestamp}</time>
              )}
            </div>
            <p className="wrap-anywhere text-sm">{event.message}</p>
            <div className="flex items-center gap-4">
              <input
                type="range"
                aria-label="Explore retained events"
                aria-valuetext={`Event ${event.id}, ${event.type}`}
                min={0}
                max={Math.max(entries.length - 1, 0)}
                value={index}
                onChange={(e) => setPinned(entries[Number(e.target.value)].id)}
                className="min-w-0 flex-1 accent-[#69f8ce]"
              />
              <button
                type="button"
                aria-pressed={pinned === null}
                onClick={() => setPinned(pinned === null ? event.id : null)}
                className="rounded border border-[#49756b] px-2 py-1 text-xs"
              >
                {pinned === null ? "Pause follow" : "Follow latest"}
              </button>
            </div>
          </>
        ) : (
          <p className="text-sm">Waiting for telemetry…</p>
        )}
      </div>
    </section>
  );
}
