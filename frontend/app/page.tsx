const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6 py-16">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">RingSentinel</h1>
        <p className="mt-2 text-sm text-neutral-400">
          Coordinated fraud-ring detection for the Razorpay AI Risk Manager track.
        </p>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
        <p className="text-sm text-neutral-300">
          <span className="font-medium text-neutral-100">Phase 1 — scaffolding.</span>{" "}
          The database schema and services are running. Detection, case files, and
          the review queue are not built yet.
        </p>
      </div>

      <div className="flex flex-col gap-2 text-sm">
        <a
          className="text-blue-400 underline underline-offset-4"
          href={`${API_BASE_URL}/docs`}
        >
          Backend API docs
        </a>
        <a
          className="text-blue-400 underline underline-offset-4"
          href={`${API_BASE_URL}/health/db`}
        >
          Database schema health
        </a>
      </div>

      <p className="text-xs text-neutral-500">
        Nothing here auto-blocks a customer. Every flag requires human approval.
      </p>
    </main>
  );
}
