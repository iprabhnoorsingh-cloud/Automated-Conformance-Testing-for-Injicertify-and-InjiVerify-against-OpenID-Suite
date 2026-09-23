"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Navigation } from "@/components/Navigation";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ApiError,
  COMPONENTS,
  TestRun,
  listTestRuns,
} from "@/lib/testRuns";

export default function TestRunsPage() {
  const [runs, setRuns] = useState<TestRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTestRuns()
      .then(setRuns)
      .catch((err) => {
        setError(
          err instanceof ApiError
            ? err.message
            : "Failed to load test runs.",
        );
      });
  }, []);

  return (
    <>
      <Navigation />
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-10">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Test Runs</h1>
            <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
              Configured test runs. Execution uses a local deterministic
              mock — no real OpenID or MOSIP systems are called yet.
            </p>
          </div>
          <Link
            href="/test-runs/new"
            className="border border-neutral-800 px-3 py-1.5 text-sm font-medium dark:border-neutral-200"
          >
            New Test Run
          </Link>
        </div>

        {error && (
          <div className="border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            {error}
          </div>
        )}

        {!error && runs === null && (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Loading...
          </p>
        )}

        {runs !== null && runs.length === 0 && (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            No test runs configured yet.
          </p>
        )}

        {runs !== null && runs.length > 0 && (
          <div className="overflow-x-auto border border-neutral-200 dark:border-neutral-800">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-neutral-200 text-neutral-500 dark:border-neutral-800 dark:text-neutral-400">
                <tr>
                  <th className="px-4 py-2 font-medium">Run Name</th>
                  <th className="px-4 py-2 font-medium">Environment</th>
                  <th className="px-4 py-2 font-medium">Components</th>
                  <th className="px-4 py-2 font-medium">Test Suites</th>
                  <th className="px-4 py-2 font-medium">Benchmark</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Created At</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-neutral-100 last:border-0 dark:border-neutral-900"
                  >
                    <td className="px-4 py-2">
                      <Link
                        href={`/test-runs/${run.id}`}
                        className="font-medium underline-offset-2 hover:underline"
                      >
                        {run.run_name}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{run.environment}</td>
                    <td className="px-4 py-2">
                      {run.components
                        .map((c) => COMPONENTS[c] ?? c)
                        .join(", ")}
                    </td>
                    <td className="px-4 py-2">
                      {run.test_suites.map((s) => s.display_name).join(", ")}
                    </td>
                    <td className="px-4 py-2">
                      {run.benchmark.minimum_pass_rate}% min /{" "}
                      {run.benchmark.critical_failures_allowed} crit
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-2 text-neutral-500 dark:text-neutral-400">
                      {new Date(run.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}
