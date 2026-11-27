type ErrorBannerProps = {
  message: string;
  code?: string;
  className?: string;
};

export function ErrorBanner({ message, code, className }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className={`rounded-md border border-(--danger)/40 bg-(--danger-soft) px-4 py-3 text-sm text-(--danger)${className ? ` ${className}` : ""}`}
    >
      <p>{message}</p>
      {code ? (
        <p className="mt-1 font-mono text-xs opacity-80">code: {code}</p>
      ) : null}
    </div>
  );
}
