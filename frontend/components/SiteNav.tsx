"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { listRepos } from "@/lib/api";
import { KillhubLogo } from "./KillhubLogo";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/features", label: "Features" },
  { href: "/hubs", label: "Hubs" },
] as const;

const HUBS_COUNT_POLL_MS = 8000;

function isActivePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function useHubsTotal() {
  const [total, setTotal] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const next = await listRepos(1, 0);
        if (!cancelled) setTotal(next.total);
      } catch {
        // Keep last known count; nav stays usable without it.
      }
    }

    void load();
    const timer = setInterval(() => {
      void load();
    }, HUBS_COUNT_POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return total;
}

export function SiteNav() {
  const pathname = usePathname();
  const hubsTotal = useHubsTotal();

  return (
    <nav className="flex items-center justify-between gap-4 py-6">
      <Link href="/" className="no-underline" aria-label="Killhub home">
        <KillhubLogo size={26} />
      </Link>
      <div className="flex items-center gap-1 sm:gap-2">
        <ul className="m-0 flex list-none items-center gap-1 p-0">
          {LINKS.map((link) => {
            const active = isActivePath(pathname, link.href);
            const showCount = link.href === "/hubs" && hubsTotal != null;
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  aria-label={
                    showCount
                      ? `Hubs, ${hubsTotal} ${hubsTotal === 1 ? "project" : "projects"} tested`
                      : undefined
                  }
                  className={
                    active
                      ? "inline-flex items-center gap-1.5 rounded-md bg-(--paper-deep) px-2.5 py-1.5 text-sm font-medium text-(--ink) ring-1 ring-(--line) no-underline"
                      : "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:bg-(--paper-deep)/60 hover:text-(--ink)"
                  }
                >
                  {link.label}
                  {showCount ? (
                    <span className="tabular-nums opacity-70">{hubsTotal}</span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
        <a
          href="https://github.com/ludvigodin/killhub"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:bg-(--paper-deep)/60 hover:text-(--ink)"
          aria-label="Killhub on GitHub"
        >
          <svg
            viewBox="0 0 16 16"
            width="16"
            height="16"
            fill="currentColor"
            aria-hidden
            focusable="false"
          >
            <title>GitHub</title>
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8" />
          </svg>
          GitHub
        </a>
      </div>
    </nav>
  );
}
