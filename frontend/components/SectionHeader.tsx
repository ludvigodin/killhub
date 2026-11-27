import type { ReactNode } from "react";

export type SectionHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  meta?: ReactNode;
  /** lg = receipt title; md = card sections; sm = nested receipt blocks */
  size?: "lg" | "md" | "sm";
  className?: string;
};

export function SectionHeader({
  eyebrow,
  title,
  description,
  meta,
  size = "md",
  className,
}: SectionHeaderProps) {
  const Heading = size === "sm" ? "h3" : "h2";
  const titleClass =
    size === "lg"
      ? "type-display text-2xl font-semibold tracking-tight"
      : size === "sm"
        ? "type-display text-base font-semibold tracking-tight"
        : "type-section-title";

  return (
    <div className={className}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="type-eyebrow text-(--muted)">{eyebrow}</p>
          ) : null}
          <Heading className={`${eyebrow ? "mt-1" : ""} ${titleClass}`}>
            {title}
          </Heading>
          {description ? (
            <div className="mt-1 text-sm text-(--muted)">{description}</div>
          ) : null}
        </div>
        {meta ? <div className="shrink-0">{meta}</div> : null}
      </div>
    </div>
  );
}
