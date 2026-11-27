"use client";

import { useEffect, useState } from "react";

export type SectionNavItem = {
  id: string;
  label: string;
};

/** Clears sticky SiteNav when scrolling to hash targets. */
export const SECTION_SCROLL_MT = "scroll-mt-28";

type SectionNavProps = {
  items: SectionNavItem[];
};

export function SectionNav({ items }: SectionNavProps) {
  const [activeId, setActiveId] = useState<string | null>(items[0]?.id ?? null);

  const itemKey = items.map((item) => item.id).join("|");

  // Stabilize on id list — avoid rebinding IntersectionObserver every render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: itemKey encodes items[].id
  useEffect(() => {
    if (items.length === 0) return;

    const elements = items
      .map((item) => document.getElementById(item.id))
      .filter((el): el is HTMLElement => el != null);
    if (elements.length === 0) return;

    const visible = new Map<string, number>();
    const order = items.map((item) => item.id);

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id;
          if (!id) continue;
          if (entry.isIntersecting) {
            visible.set(id, entry.intersectionRatio);
          } else {
            visible.delete(id);
          }
        }
        if (visible.size === 0) return;
        let bestId = order[0] ?? null;
        let bestRatio = -1;
        for (const id of order) {
          const ratio = visible.get(id);
          if (ratio != null && ratio >= bestRatio) {
            bestRatio = ratio;
            bestId = id;
          }
        }
        if (bestId) setActiveId(bestId);
      },
      {
        rootMargin: "-25% 0px -55% 0px",
        threshold: [0, 0.1, 0.25, 0.5, 1],
      },
    );

    for (const el of elements) observer.observe(el);
    return () => observer.disconnect();
  }, [itemKey]);

  if (items.length === 0) return null;

  function jumpTo(event: React.MouseEvent<HTMLAnchorElement>, id: string) {
    event.preventDefault();
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", `#${id}`);
    setActiveId(id);
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

      <aside className="hidden lg:block">
        <nav
          aria-label="Page sections"
          className="sticky top-28 max-h-[calc(100vh-8rem)] overflow-y-auto py-1"
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
