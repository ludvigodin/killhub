import { UrlForm } from "@/components/UrlForm";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center px-6 py-16">
      <p
        className="mb-3 text-5xl font-semibold tracking-tight sm:text-6xl"
        style={{ fontFamily: "var(--font-display), ui-sans-serif, sans-serif" }}
      >
        Killhub
      </p>
      <p className="mb-10 max-w-xl text-lg leading-relaxed text-[var(--muted)]">
        Paste a public GitHub URL. Get a verified running environment — and a
        receipt that outlives the sandbox.
      </p>

      <UrlForm />
    </main>
  );
}
