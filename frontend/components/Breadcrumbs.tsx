import Link from "next/link";

export type BreadcrumbItem = {
  label: string;
  href?: string;
  /** Full label for title / screen readers when `label` is truncated. */
  title?: string;
};

type BreadcrumbsProps = {
  items: BreadcrumbItem[];
};

export function Breadcrumbs({ items }: BreadcrumbsProps) {
  if (items.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="m-0 flex list-none flex-wrap items-center gap-x-1.5 gap-y-1 p-0 text-sm">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li
              key={`${item.label}-${index}`}
              className="flex items-center gap-1.5"
            >
              {index > 0 ? (
                <span aria-hidden className="select-none text-(--muted)/60">
                  /
                </span>
              ) : null}
              {last || !item.href ? (
                <span
                  className={
                    last
                      ? "max-w-44 truncate font-mono text-(--ink) sm:max-w-none"
                      : "max-w-40 truncate text-(--muted) sm:max-w-64"
                  }
                  aria-current={last ? "page" : undefined}
                  title={item.title ?? item.label}
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  href={item.href}
                  className="max-w-40 truncate text-(--muted) no-underline transition hover:text-(--ink) sm:max-w-64"
                  title={item.title ?? item.label}
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
