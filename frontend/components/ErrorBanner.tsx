type ErrorBannerProps = {
  message: string;
  code?: string;
};

export function ErrorBanner({ message, code }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className="mt-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900"
    >
      <p>{message}</p>
      {code ? (
        <p className="mt-1 font-mono text-xs text-red-700">code: {code}</p>
      ) : null}
    </div>
  );
}
