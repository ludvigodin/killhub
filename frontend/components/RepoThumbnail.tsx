import type { CSSProperties } from "react";

export function RepoThumbnail({ repo }: { repo: string }) {
  let seed = 2166136261;
  for (const char of repo.toLowerCase()) {
    seed = Math.imul(seed ^ char.charCodeAt(0), 16777619) >>> 0;
  }

  const style = {
    "--planet-hue": seed % 360,
    "--orbit-angle": `${((seed >>> 8) % 62) - 31}deg`,
    "--moon-x": `${(seed & 1 ? 13 : 73) + ((seed >>> 16) % 10)}%`,
    "--moon-y": `${12 + ((seed >>> 24) % 22)}%`,
  } as CSSProperties;

  return (
    <div className="repo-space" style={style} aria-hidden="true">
      <span className="repo-moon" />
      <div className="repo-orbit">
        <span className="repo-planet" />
        <span className="repo-ring" />
      </div>
    </div>
  );
}
