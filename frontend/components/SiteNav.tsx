"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { KillhubLogo } from "./KillhubLogo";

const LINKS = [{ href: "/features", label: "Features" }] as const;

export function SiteNav() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center justify-between gap-4 py-6">
      <Link href="/" className="no-underline" aria-label="Killhub home">
        <KillhubLogo size={28} withWordmark />
      </Link>
      <div className="flex items-center gap-1 sm:gap-2">
        <ul className="m-0 flex list-none items-center gap-1 p-0">
          {LINKS.map((link) => {
            const active =
              pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className={
                    active
                      ? "rounded-md px-2.5 py-1.5 text-sm font-medium text-(--ink) no-underline"
                      : "rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:text-(--ink)"
                  }
                  aria-current={active ? "page" : undefined}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
        <a
          href="https://github.com/ludvigodin/killhub"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:text-(--ink)"
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
