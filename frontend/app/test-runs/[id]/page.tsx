"use client";

import { useParams, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { Navigation } from "@/components/Navigation";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ApiError,
  COMPONENTS,
  Execution,
  TestRun,
  deleteTestRun,
  executeTestRun,
  getLatestExecution,
  getTestRun,
} from "@/lib/testRuns";

export default function TestRunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const runId = params.id;

  const [run, setRun] = useState<TestRun | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    Promise.all([getTestRun(runId), getLatestExecution(runId)])
      .then(([runData, executionData]) => {
        setRun(runData);
        setExecution(executionData);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(
          err instanceof ApiError ? err.message : "Failed to load test run.",
        );
      });
  }, [runId]);

  async function handleExecute() {
    setExecuting(true);
    setError(null);
    try {
      const result = await executeTestRun(runId);
      setExecution(result);
      const runData = await getTestRun(runId);
      setRun(runData);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to execute test run.",
      );
    } finally {
      setExecuting(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this test run configuration?")) return;
    setDeleting(true);
    try {
      await deleteTestRun(runId);
      router.push("/test-runs");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to delete test run.",
      );
      setDeleting(false);
    }
  }

  if (notFound) {
    return (
      <>
        <Navigation />
        <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-6 py-10">
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Test run not found.
          </p>
        </main>
      </>
    );
  }

  return (
    <>
      <Navigation />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-10">
        {error && (
          <div className="border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            {error}
          </div>
        )}

        {!run && !error && (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Loading...
          </p>
        )}

        {run && (
          <>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold">{run.run_name}</h1>
                <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
                  {run.environment}
                </p>
              </div>
              <StatusBadge status={run.status} />
            </div>

            <section className="border border-neutral-200 dark:border-neutral-800">
              <dl className="divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
                <Row label="Components">
                  {run.components.map((c) => COMPONENTS[c] ?? c).join(", ")}
                </Row>
                <Row label="Test Suites">
                  <ul className="flex flex-col gap-1">
                    {run.test_suites.map((s) => (
                      <li key={`${s.provider}:${s.suite_id}`}>
                        {s.display_name}{" "}
                        <span className="text-neutral-500 dark:text-neutral-400">
                          ({s.provider}:{s.suite_id}
                          {s.version ? `@${s.version}` : ""})
                        </span>
                      </li>
                    ))}
                  </ul>
                </Row>
                <Row label="Benchmark">
                  Minimum pass rate: {run.benchmark.minimum_pass_rate}% ·
                  Critical failures allowed:{" "}
                  {run.benchmark.critical_failures_allowed}
                </Row>
                {run.metadata?.notes && (
                  <Row label="Notes">{run.metadata.notes}</Row>
                )}
                {run.metadata?.created_by && (
                  <Row label="Created By">{run.metadata.created_by}</Row>
                )}
                <Row label="Created At">
                  {new Date(run.created_at).toLocaleString()}
                </Row>
              </dl>
            </section>

            <div className="flex gap-3">
              <button
                onClick={handleExecute}
                disabled={executing}
                className="border border-neutral-800 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-neutral-200"
              >
                {executing ? "Executing..." : "Execute"}
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="border border-red-300 px-4 py-2 text-sm font-medium text-red-700 disabled:opacity-50 dark:border-red-900 dark:text-red-400"
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>

            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              Execution runs a local, deterministic mock — no real OpenID
              Foundation or MOSIP/Inji systems are called yet.
            </p>

            {execution && (
              <section className="flex flex-col gap-3 border border-neutral-200 p-4 dark:border-neutral-800">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-medium">Latest Execution</h2>
                  <StatusBadge status={execution.status} />
                </div>
                <p className="text-sm text-neutral-500 dark:text-neutral-400">
                  {execution.completed_steps} / {execution.total_steps} steps
                  completed
                  {execution.completed_at &&
                    ` · finished ${new Date(execution.completed_at).toLocaleString()}`}
                </p>

                <ul className="flex flex-col gap-2">
                  {execution.steps.map((step) => {
                    const result = execution.step_results.find(
                      (r) => r.step_id === step.step_id,
                    );
                    return (
                      <li
                        key={step.step_id}
                        className="flex flex-col gap-1 border border-neutral-100 p-3 text-sm dark:border-neutral-900"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">
                            {step.order + 1}. {step.display_name}
                          </span>
                          <StatusBadge status={step.status} />
                        </div>
                        {result && (
                          <p className="text-neutral-500 dark:text-neutral-400">
                            {result.message}
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-4 px-4 py-3">
      <dt className="text-neutral-500 dark:text-neutral-400">{label}</dt>
      <dd className="col-span-2">{children}</dd>
    </div>
  );
}
