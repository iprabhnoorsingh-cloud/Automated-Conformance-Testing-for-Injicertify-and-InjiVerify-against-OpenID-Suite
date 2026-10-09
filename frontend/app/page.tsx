"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Navigation } from "@/components/Navigation";
import { StatusBadge } from "@/components/StatusBadge";
import { BackendStatus } from "@/components/BackendStatus";
import {
  ApiError,
  Execution,
  listAllExecutions,
} from "@/lib/testRuns";

export default function DashboardPage() {
  const [executions, setExecutions] = useState<Execution[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAllExecutions()
      .then(setExecutions)
      .catch((err) => {
        setError(
          err instanceof ApiError
            ? err.message
            : "Failed to load executions.",
        );
      });
  }, []);

  const total = executions?.length || 0;
  const passed = executions?.filter((e) => e.status === "PASSED").length || 0;
  const failed = executions?.filter((e) => e.status === "FAILED").length || 0;
  const queued = executions?.filter((e) => e.status === "QUEUED").length || 0;
  const running = executions?.filter((e) => e.status === "RUNNING").length || 0;

  const m7Passed = executions?.filter((e) => e.benchmark_evaluation?.status === "PASSED").length || 0;
  const m7Failed = executions?.filter((e) => e.benchmark_evaluation?.status === "FAILED").length || 0;

  const recentActivity = executions?.slice(0, 10) || [];
  const recentFailures = executions?.filter((e) => e.status === "FAILED" || e.benchmark_evaluation?.status === "FAILED").slice(0, 5) || [];

  return (
    <>
      <Navigation />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10">
        <div>
          <h1 className="text-xl font-semibold">Conformance Dashboard</h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Overview of test run orchestration, benchmark gates, and reporting.
          </p>
        </div>

        {error && (
          <div className="border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          <div className="border border-neutral-200 px-4 py-6 dark:border-neutral-800">
            <h3 className="text-sm font-medium text-neutral-500 dark:text-neutral-400">System Status</h3>
            <div className="mt-2">
              <BackendStatus />
            </div>
          </div>
          <div className="border border-neutral-200 px-4 py-6 dark:border-neutral-800">
            <h3 className="text-sm font-medium text-neutral-500 dark:text-neutral-400">Total Executions</h3>
            <p className="mt-2 text-3xl font-semibold">{executions === null ? "..." : total}</p>
          </div>
          <div className="border border-neutral-200 px-4 py-6 dark:border-neutral-800">
            <h3 className="text-sm font-medium text-neutral-500 dark:text-neutral-400">Execution Status</h3>
            <div className="mt-2 flex flex-col gap-1 text-sm">
              <div className="flex justify-between"><span>Passed:</span> <span className="text-green-600 dark:text-green-400">{passed}</span></div>
              <div className="flex justify-between"><span>Failed:</span> <span className="text-red-600 dark:text-red-400">{failed}</span></div>
              <div className="flex justify-between"><span>Queued:</span> <span className="text-amber-600 dark:text-amber-400">{queued}</span></div>
              <div className="flex justify-between"><span>Running:</span> <span className="text-blue-600 dark:text-blue-400">{running}</span></div>
            </div>
          </div>
          <div className="border border-neutral-200 px-4 py-6 dark:border-neutral-800">
            <h3 className="text-sm font-medium text-neutral-500 dark:text-neutral-400">M7 Conformance Gate</h3>
            <div className="mt-2 flex flex-col gap-1 text-sm">
              <div className="flex justify-between"><span>Met Benchmark:</span> <span className="text-green-600 dark:text-green-400">{m7Passed}</span></div>
              <div className="flex justify-between"><span>Failed Benchmark:</span> <span className="text-red-600 dark:text-red-400">{m7Failed}</span></div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          <section>
            <h2 className="mb-4 text-lg font-semibold">Recent Activity</h2>
            {executions === null && <p className="text-sm text-neutral-500">Loading...</p>}
            {executions !== null && recentActivity.length === 0 && <p className="text-sm text-neutral-500">No executions found.</p>}
            {recentActivity.length > 0 && (
              <div className="overflow-x-auto border border-neutral-200 dark:border-neutral-800">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-neutral-200 text-neutral-500 dark:border-neutral-800 dark:text-neutral-400">
                    <tr>
                      <th className="px-4 py-2 font-medium">Execution ID</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2 font-medium">M7 Gate</th>
                      <th className="px-4 py-2 font-medium">Started At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentActivity.map((run) => (
                      <tr key={run.id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-900">
                        <td className="px-4 py-2">
                          <Link href={`/test-runs/${run.test_run_id}`} className="font-mono text-xs underline-offset-2 hover:underline">
                            {run.id.substring(0, 8)}...
                          </Link>
                        </td>
                        <td className="px-4 py-2"><StatusBadge status={run.status} /></td>
                        <td className="px-4 py-2">
                          {run.benchmark_evaluation ? (
                            <StatusBadge status={run.benchmark_evaluation.status} />
                          ) : (
                            <span className="text-neutral-400">-</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-neutral-500 text-xs">
                          {new Date(run.started_at).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h2 className="mb-4 text-lg font-semibold">Recent Failures</h2>
            {executions === null && <p className="text-sm text-neutral-500">Loading...</p>}
            {executions !== null && recentFailures.length === 0 && <p className="text-sm text-neutral-500">No recent failures.</p>}
            {recentFailures.length > 0 && (
              <div className="flex flex-col gap-4">
                {recentFailures.map((run) => (
                  <div key={run.id} className="border border-red-200 bg-red-50/50 px-4 py-3 text-sm dark:border-red-900/50 dark:bg-red-950/20">
                    <div className="flex items-center justify-between mb-2">
                      <Link href={`/test-runs/${run.test_run_id}`} className="font-mono font-medium underline-offset-2 hover:underline text-red-800 dark:text-red-200">
                        {run.id}
                      </Link>
                      <span className="text-xs text-neutral-500">{new Date(run.started_at).toLocaleString()}</span>
                    </div>
                    {run.benchmark_evaluation?.status === "FAILED" && (
                      <div className="mt-2 text-xs">
                        <p className="font-medium text-red-800 dark:text-red-200 mb-1">M7 Benchmark Gate Failed:</p>
                        <ul className="list-disc pl-4 text-red-700 dark:text-red-300">
                          {run.benchmark_evaluation.violations.map((v, i) => (
                            <li key={i}>{v.message}</li>
                          ))}
                          {run.benchmark_evaluation.violations.length === 0 && (
                            <li>Pass rate {run.benchmark_evaluation.pass_rate.toFixed(1)}% &lt; {run.benchmark_evaluation.minimum_pass_rate.toFixed(1)}%</li>
                          )}
                        </ul>
                      </div>
                    )}
                    {run.status === "FAILED" && !run.benchmark_evaluation && (
                      <div className="mt-2 text-xs text-red-700 dark:text-red-300">
                        Execution failed before or during benchmark evaluation.
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}
