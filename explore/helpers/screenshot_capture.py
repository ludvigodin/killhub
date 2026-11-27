#!/usr/bin/env python3
"""In-guest Playwright still capture (D18, D38). Runs only inside Plane 2."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a PNG still of a local URL")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout-ms", type=int, default=15_000)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    url = args.url.strip()
    out = args.out.strip()
    if not url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        print("refusing non-loopback url", file=sys.stderr)
        return 2
    if not out.startswith("/tmp/killhub/"):
        print("out must be under /tmp/killhub/", file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(out) or "/tmp/killhub", exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright_missing", file=sys.stderr)
        return 3

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    chromium_channel = os.environ.get("KILLHUB_CHROMIUM_CHANNEL", "").strip() or None
    executable = os.environ.get("KILLHUB_CHROMIUM_PATH", "").strip() or None

    try:
        with sync_playwright() as p:
            launch_kwargs: dict = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if executable:
                launch_kwargs["executable_path"] = executable
            elif chromium_channel:
                launch_kwargs["channel"] = chromium_channel
            if browsers_path:
                # Browsers installed under Killhub tooling dir during install phase.
                os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers_path)
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(viewport={"width": args.width, "height": args.height})
                page.goto(url, wait_until="networkidle", timeout=args.timeout_ms)
                page.screenshot(path=out, full_page=False, type="png")
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — surface to harness as capture failure
        print(f"capture_failed:{exc.__class__.__name__}:{exc}", file=sys.stderr)
        return 1

    if not os.path.isfile(out) or os.path.getsize(out) < 32:
        print("empty_screenshot", file=sys.stderr)
        return 1
    print(f"ok:{out}:{os.path.getsize(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
