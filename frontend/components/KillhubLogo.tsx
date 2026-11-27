type KillhubLogoProps = {
  /** Visual size of the mark in pixels. */
  size?: number;
  /** Show the Killhub wordmark beside the mark. */
  withWordmark?: boolean;
  /** Wordmark size classes; ignored when withWordmark is false. */
  wordmarkClassName?: string;
  className?: string;
};

/**
 * Brand mark: geometric K in a gated teal containment frame.
 * Prefer this over raster assets for UI chrome.
 */
export function KillhubLogo({
  size = 28,
  withWordmark = false,
  wordmarkClassName = "text-sm font-semibold tracking-tight",
  className,
}: KillhubLogoProps) {
  return (
    <span
      className={["inline-flex items-center gap-2.5", className]
        .filter(Boolean)
        .join(" ")}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 128 128"
        aria-hidden={withWordmark ? true : undefined}
        role={withWordmark ? undefined : "img"}
        aria-label={withWordmark ? undefined : "Killhub"}
        className="shrink-0"
      >
        {!withWordmark ? <title>Killhub</title> : null}
        <rect width="128" height="128" rx="28" fill="#0a0b0d" />
        <path
          fill="none"
          stroke="#3d9b9b"
          strokeWidth="5"
          strokeLinecap="round"
          d="M96 34 H48 A14 14 0 0 0 34 48 V80 A14 14 0 0 0 48 94 H80 A14 14 0 0 0 94 80 V64"
        />
        <path
          fill="#f2f4f7"
          fillRule="evenodd"
          d="M40 34h18v22L78 34h19L71.5 60.5 99 94H79.5L58 70V94H40V34zm12.5 20 7 6.8-7 6.7V54z"
        />
        <circle cx="65" cy="73" r="4.25" fill="#3d9b9b" />
      </svg>
      {withWordmark ? (
        <span
          className={wordmarkClassName}
          style={{
            fontFamily: "var(--font-display), ui-sans-serif, sans-serif",
          }}
        >
          Killhub
        </span>
      ) : null}
    </span>
  );
}
