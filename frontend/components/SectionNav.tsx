"use client";

import { useEffect, useState } from "react";

export type SectionNavItem = {
  id: string;
  label: string;
};

/** Clears sticky SiteNav when scrolling to hash targets. */
export const SECTION_SCROLL_MT = "scroll-mt-28";

/** Matches `top-28` sticky offset (SiteNav clearance). */
const STICKY_OFFSET_PX = 112;

type SectionNavProps = {
  items: SectionNavItem[];
};

function activeSectionId(ids: string[]): string | null {
  let current: string | null = ids[0] ?? null;
  for (const id of ids) {
    const el = document.getElementById(id);
    if (!el) continue;
    // Last section whose top has reached / passed the sticky line wins.
    if (el.getBoundingClientRect().top - STICKY_OFFSET_PX <= 1) {
      current = id;
    }
  }
  return current;
}

export function SectionNav({ items }: SectionNavProps) {
  const [activeId, setActiveId] = useState<string | null>(items[0]?.id ?? null);

  const itemKey = items.map((item) => item.id).join("|");

  // Stabilize on id list — avoid rebinding scroll listeners every render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: itemKey encodes items[].id
  useEffect(() => {
    if (items.length === 0) return;

    const ids = items.map((item) => item.id);
    let frame = 0;

    function update() {
      frame = 0;
      const next = activeSectionId(ids);
      if (next) setActiveId(next);
    }

    function onScrollOrResize() {
      if (frame) return;
      frame = window.requestAnimationFrame(update);
    }

    update();
    // Sections can mount a tick after the nav (async job data) — retry once.
    const retry = window.setTimeout(update, 50);

    window.addEventListener("scroll", onScrollOrResize, { passive: true });
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      window.clearTimeout(retry);
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScrollOrResize);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [itemKey]);

  if (items.length === 0) return null;

  function jumpTo(event: React.MouseEvent<HTMLAnchorElement>, id: string) {
    event.preventDefault();
    const el = document.getElementById(id);
    if (!el) return;
    setActiveId(id);
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", `#${id}`);
  }

  return (
    <>
      <nav
        aria-label="Page sections"
        className="sticky top-[4.75rem] z-40 -mx-6 mb-2 border-b border-(--line)/50 bg-(--paper)/85 px-6 py-2.5 backdrop-blur-md lg:hidden"
      >
        <ul className="m-0 flex list-none gap-1.5 overflow-x-auto p-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {items.map((item) => {
            const active = item.id === activeId;
            return (
              <li key={item.id} className="shrink-0">
                <a
                  href={`#${item.id}`}
                  onClick={(e) => jumpTo(e, item.id)}
                  aria-current={active ? "true" : undefined}
                  className={
                    active
                      ? "type-mono inline-flex rounded-md border border-(--accent)/50 bg-(--accent-soft) px-2.5 py-1 tracking-wide text-(--accent) no-underline"
                      : "type-mono inline-flex rounded-md border border-(--line) bg-(--paper-deep)/60 px-2.5 py-1 tracking-wide text-(--muted) no-underline transition-colors hover:border-(--accent)/40 hover:text-(--ink)"
                  }
                >
                  {item.label}
                </a>
              </li>
            );
          })}
        </ul>
      </nav>

      <aside className="hidden lg:block lg:self-stretch">
        <nav
          aria-label="Page sections"
          className="sticky top-28 z-30 max-h-[calc(100vh-8rem)] overflow-y-auto py-1"
        >
          <p className="type-eyebrow mb-3 text-(--muted)">On this page</p>
          <ul className="m-0 flex list-none flex-col gap-0.5 border-l border-(--line) p-0">
            {items.map((item) => {
              const active = item.id === activeId;
              return (
                <li key={item.id}>
                  <a
                    href={`#${item.id}`}
                    onClick={(e) => jumpTo(e, item.id)}
                    aria-current={active ? "true" : undefined}
                    className={
                      active
                        ? "-ml-px block border-l-2 border-(--accent) py-1.5 pl-3 text-sm font-medium text-(--ink) no-underline"
                        : "-ml-px block border-l-2 border-transparent py-1.5 pl-3 text-sm text-(--muted) no-underline transition-colors hover:border-(--line) hover:text-(--ink)"
                    }
                  >
                    {item.label}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
    </>
  );
}
