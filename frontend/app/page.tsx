import { Navigation } from "@/components/Navigation";
import { BackendStatus } from "@/components/BackendStatus";

export default function DashboardPage() {
  return (
    <>
      <Navigation />
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-10">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Conformance-testing orchestration for the MOSIP/Inji ecosystem.
          </p>
        </div>

        <section className="max-w-sm">
          <h2 className="mb-2 text-sm font-medium text-neutral-500 dark:text-neutral-400">
            System status
          </h2>
          <BackendStatus />
        </section>

        <section className="border border-dashed border-neutral-300 px-4 py-6 text-sm text-neutral-500 dark:border-neutral-700 dark:text-neutral-400">
          Test run orchestration, benchmark gates, and reporting are not
          implemented in this milestone. This dashboard currently provides
          only the project foundation: navigation shell and a backend health
          check.
        </section>
      </main>
    </>
  );
}
