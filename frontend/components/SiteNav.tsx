"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useId, useState } from "react";
import { listRepos } from "@/lib/api";
import { fetchGithubStars, KILLHUB_GITHUB_URL } from "@/lib/githubStars";
import { KillhubLogo } from "./KillhubLogo";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/features", label: "Features" },
  { href: "/hubs", label: "Hubs" },
] as const;

const HUBS_COUNT_POLL_MS = 8000;
const GITHUB_STARS_POLL_MS = 60 * 60 * 1000;

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

function useGithubStars() {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      try {
        const next = await fetchGithubStars(controller.signal);
        if (!cancelled) setStars(next);
      } catch {
        // Keep last known count; link stays usable without stars.
      }
    }

    void load();
    const timer = setInterval(() => {
      void load();
    }, GITHUB_STARS_POLL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  return stars;
}

function useScrolledPast(threshold = 12) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const update = () => {
      setScrolled(window.scrollY > threshold);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, [threshold]);

  return scrolled;
}

function GithubMark({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="currentColor"
      aria-hidden
      focusable="false"
    >
      <title>GitHub</title>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8" />
    </svg>
  );
}

function StarMark() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="12"
      height="12"
      fill="currentColor"
      aria-hidden
      focusable="false"
    >
      <title>Stars</title>
      <path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z" />
    </svg>
  );
}

function navLinkClass(active: boolean) {
  return active
    ? "inline-flex items-center gap-1.5 rounded-md bg-(--paper-deep) px-2.5 py-1.5 text-sm font-medium text-(--ink) ring-1 ring-(--line) no-underline"
    : "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:bg-(--paper-deep)/60 hover:text-(--ink)";
}

function mobileNavLinkClass(active: boolean) {
  return active
    ? "flex items-center justify-between gap-2 rounded-md bg-(--paper-deep) px-3 py-2.5 text-sm font-medium text-(--ink) ring-1 ring-(--line) no-underline"
    : "flex items-center justify-between gap-2 rounded-md px-3 py-2.5 text-sm text-(--muted) no-underline transition hover:bg-(--paper-deep)/60 hover:text-(--ink)";
}

function SiteNavFrame({
  pathname,
  hubsTotal,
  githubStars,
  scrolled,
}: {
  pathname: string;
  hubsTotal: number | null;
  githubStars: number | null;
  scrolled: boolean;
}) {
  const showStars = githubStars != null;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();

  // Close the drawer after client navigations (including browser back/forward).
  // biome-ignore lint/correctness/useExhaustiveDependencies: pathname is the intentional trigger
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    function onChange() {
      if (mq.matches) setMenuOpen(false);
    }
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const githubAria = showStars
    ? `Killhub on GitHub, ${githubStars} ${githubStars === 1 ? "star" : "stars"}`
    : "Killhub on GitHub";

  return (
    <nav className="sticky top-0 z-50 ml-[calc(50%-50vw)] w-screen">
      <div
        aria-hidden
        className={
          scrolled || menuOpen
            ? "pointer-events-none absolute inset-0 -z-10 border-b border-(--line)/45 bg-(--paper)/70 opacity-100 backdrop-blur-md backdrop-saturate-150 transition-opacity duration-300 ease-out"
            : "pointer-events-none absolute inset-0 -z-10 border-b border-transparent bg-(--paper)/70 opacity-0 backdrop-blur-md backdrop-saturate-150 transition-opacity duration-300 ease-out"
        }
      />
      <div className="relative mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-4 sm:px-6 sm:py-5 md:gap-4 md:py-6">
        <Link
          href="/"
          className="shrink-0 no-underline"
          aria-label="Killhub home"
        >
          <KillhubLogo size={26} />
        </Link>

        <div className="hidden items-center gap-1 sm:gap-2 md:flex">
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
                    className={navLinkClass(active)}
                  >
                    {link.label}
                    {showCount ? (
                      <span className="tabular-nums opacity-70">
                        {hubsTotal}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
          <a
            href={KILLHUB_GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm text-(--muted) no-underline transition hover:bg-(--paper-deep)/60 hover:text-(--ink)"
            aria-label={githubAria}
          >
            <GithubMark />
            <span className="inline-flex items-center gap-1.5">
              GitHub
              {showStars ? (
                <span className="inline-flex items-center gap-1 tabular-nums opacity-70">
                  <StarMark />
                  {githubStars}
                </span>
              ) : null}
            </span>
          </a>
        </div>

        <div className="flex items-center gap-0.5 md:hidden">
          <a
            href={KILLHUB_GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex size-10 items-center justify-center rounded-md text-(--muted) no-underline transition hover:bg-(--paper-deep)/60 hover:text-(--ink)"
            aria-label={githubAria}
          >
            <GithubMark size={18} />
          </a>
          <button
            type="button"
            className="inline-flex size-10 items-center justify-center rounded-md text-(--muted) transition hover:bg-(--paper-deep)/60 hover:text-(--ink)"
            aria-expanded={menuOpen}
            aria-controls={menuId}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? (
              <svg
                viewBox="0 0 24 24"
                width="20"
                height="20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                aria-hidden
                focusable="false"
              >
                <title>Close</title>
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            ) : (
              <svg
                viewBox="0 0 24 24"
                width="20"
                height="20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                aria-hidden
                focusable="false"
              >
                <title>Menu</title>
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {menuOpen ? (
        <div
          id={menuId}
          className="relative border-t border-(--line)/45 md:hidden"
        >
          <ul className="mx-auto m-0 flex w-full max-w-6xl list-none flex-col gap-1 px-4 py-3 sm:px-6">
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
                    className={mobileNavLinkClass(active)}
                    onClick={() => setMenuOpen(false)}
                  >
                    <span>{link.label}</span>
                    {showCount ? (
                      <span className="tabular-nums opacity-70">
                        {hubsTotal}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </nav>
  );
}

function SiteNavInner({ scrolled }: { scrolled: boolean }) {
  const pathname = usePathname();
  const hubsTotal = useHubsTotal();
  const githubStars = useGithubStars();
  return (
    <SiteNavFrame
      pathname={pathname}
      hubsTotal={hubsTotal}
      githubStars={githubStars}
      scrolled={scrolled}
    />
  );
}

export function SiteNav() {
  const scrolled = useScrolledPast();
  return (
    <Suspense
      fallback={
        <SiteNavFrame
          pathname=""
          hubsTotal={null}
          githubStars={null}
          scrolled={scrolled}
        />
      }
    >
      <SiteNavInner scrolled={scrolled} />
    </Suspense>
  );
}
