type KillhubLogoProps = {
  /** Visual height of the wordmark in pixels. */
  size?: number;
  /**
   * Kept for call-site compatibility. The asset is already the full wordmark,
   * so this no longer renders a separate text label.
   */
  withWordmark?: boolean;
  /** @deprecated Unused - wordmark is baked into the logo asset. */
  wordmarkClassName?: string;
  className?: string;
};

/** Intrinsic pixel size of `public/killhub-logo.png`. */
const LOGO_WIDTH = 238;
const LOGO_HEIGHT = 83;

/**
 * Brand wordmark: Kill + hub badge (monochrome).
 */
export function KillhubLogo({ size = 28, className }: KillhubLogoProps) {
  const height = size;
  const width = Math.round((LOGO_WIDTH / LOGO_HEIGHT) * height);

  return (
    // biome-ignore lint/performance/noImgElement: static public brand asset
    <img
      src="/killhub-logo.png"
      alt="Killhub"
      width={width}
      height={height}
      className={["inline-block shrink-0", className].filter(Boolean).join(" ")}
      decoding="async"
    />
  );
}
