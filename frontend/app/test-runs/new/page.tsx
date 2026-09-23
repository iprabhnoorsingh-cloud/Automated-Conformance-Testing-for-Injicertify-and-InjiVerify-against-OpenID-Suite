"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Navigation } from "@/components/Navigation";
import {
  ApiError,
  COMPONENTS,
  ENVIRONMENTS,
  Environment,
  PROVIDERS,
  TestSuiteConfig,
  createTestRun,
} from "@/lib/testRuns";

interface SuiteDraft {
  provider: string;
  suite_id: string;
  display_name: string;
  version: string;
  // OpenID Foundation Conformance Suite fields — only used/required when
  // provider === "openid". Kept as raw text here (parsed/validated on
  // submit) so the form doesn't fight the user over partially-typed JSON.
  openidPlanName: string;
  openidPlanConfiguration: string;
  openidVariant: string;
  openidModules: string;
}

const EMPTY_SUITE: SuiteDraft = {
  provider: "mock",
  suite_id: "",
  display_name: "",
  version: "",
  openidPlanName: "",
  openidPlanConfiguration: "",
  openidVariant: "",
  openidModules: "",
};

export default function NewTestRunPage() {
  const router = useRouter();

  const [runName, setRunName] = useState("");
  const [environment, setEnvironment] = useState<Environment>("development");
  const [components, setComponents] = useState<string[]>([]);
  const [suites, setSuites] = useState<SuiteDraft[]>([{ ...EMPTY_SUITE }]);
  const [minPassRate, setMinPassRate] = useState("95");
  const [criticalFailures, setCriticalFailures] = useState("0");
  const [notes, setNotes] = useState("");

  const [fieldErrors, setFieldErrors] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function toggleComponent(id: string) {
    setComponents((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
    );
  }

  function updateSuite(index: number, patch: Partial<SuiteDraft>) {
    setSuites((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    );
  }

  function addSuite() {
    setSuites((prev) => [...prev, { ...EMPTY_SUITE }]);
  }

  function removeSuite(index: number) {
    setSuites((prev) => prev.filter((_, i) => i !== index));
  }

  function parseJsonField(raw: string, fieldLabel: string, errors: string[]): unknown {
    if (!raw.trim()) return undefined;
    try {
      return JSON.parse(raw);
    } catch {
      errors.push(`${fieldLabel} must be valid JSON.`);
      return undefined;
    }
  }

  function validate(): string[] {
    const errors: string[] = [];
    if (!runName.trim()) errors.push("Run name is required.");
    if (components.length === 0)
      errors.push("Select at least one component.");

    const validSuites = suites.filter(
      (s) => s.provider.trim() && s.suite_id.trim() && s.display_name.trim(),
    );
    if (validSuites.length === 0)
      errors.push(
        "At least one test suite needs a provider, suite ID, and display name.",
      );

    validSuites.forEach((s, i) => {
      if (s.provider !== "openid") return;
      const label = `Test suite #${i + 1} ("${s.display_name || s.suite_id}")`;
      if (!s.openidPlanName.trim()) {
        errors.push(
          `${label}: OpenID plan name is required — a real Conformance Suite plan name, not invented.`,
        );
      }
      parseJsonField(s.openidPlanConfiguration, `${label} plan configuration`, errors);
      parseJsonField(s.openidVariant, `${label} variant`, errors);
    });

    const passRate = Number(minPassRate);
    if (Number.isNaN(passRate) || passRate < 0 || passRate > 100)
      errors.push("Minimum pass rate must be between 0 and 100.");

    const critical = Number(criticalFailures);
    if (!Number.isInteger(critical) || critical < 0)
      errors.push("Critical failures allowed must be a non-negative integer.");

    return errors;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    const errors = validate();
    setFieldErrors(errors);
    if (errors.length > 0) return;

    const test_suites: TestSuiteConfig[] = suites
      .filter((s) => s.provider.trim() && s.suite_id.trim() && s.display_name.trim())
      .map((s) => {
        const suite: TestSuiteConfig = {
          provider: s.provider.trim(),
          suite_id: s.suite_id.trim(),
          display_name: s.display_name.trim(),
          version: s.version.trim() || undefined,
        };
        if (s.provider === "openid") {
          // Safe to parse directly here: validate() already rejected the
          // submission if either JSON field failed to parse.
          const modules = s.openidModules
            .split(",")
            .map((m) => m.trim())
            .filter(Boolean);
          suite.openid_config = {
            plan_name: s.openidPlanName.trim(),
            plan_configuration: s.openidPlanConfiguration.trim()
              ? JSON.parse(s.openidPlanConfiguration)
              : {},
            variant: s.openidVariant.trim()
              ? JSON.parse(s.openidVariant)
              : undefined,
            modules: modules.length > 0 ? modules : undefined,
          };
        }
        return suite;
      });

    setSubmitting(true);
    try {
      const run = await createTestRun({
        run_name: runName.trim(),
        environment,
        components,
        test_suites,
        benchmark: {
          minimum_pass_rate: Number(minPassRate),
          critical_failures_allowed: Number(criticalFailures),
        },
        metadata: notes.trim() ? { notes: notes.trim() } : null,
      });
      router.push(`/test-runs/${run.id}`);
    } catch (err) {
      setSubmitError(
        err instanceof ApiError ? err.message : "Failed to create test run.",
      );
      setSubmitting(false);
    }
  }

  return (
    <>
      <Navigation />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-10">
        <div>
          <h1 className="text-xl font-semibold">New Test Run</h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Define a configuration for a future execution. This does not run
            any test yet.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="flex flex-col gap-1">
            <label htmlFor="run_name" className="text-sm font-medium">
              Run Name
            </label>
            <input
              id="run_name"
              value={runName}
              onChange={(e) => setRunName(e.target.value)}
              className="border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
              placeholder="e.g. Nightly Inji Certify check"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="environment" className="text-sm font-medium">
              Environment
            </label>
            <select
              id="environment"
              value={environment}
              onChange={(e) => setEnvironment(e.target.value as Environment)}
              className="border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
            >
              {ENVIRONMENTS.map((env) => (
                <option key={env} value={env}>
                  {env}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium">Components</legend>
            {Object.entries(COMPONENTS).map(([id, label]) => (
              <label key={id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={components.includes(id)}
                  onChange={() => toggleComponent(id)}
                />
                {label}
              </label>
            ))}
          </fieldset>

          <fieldset className="flex flex-col gap-3">
            <legend className="text-sm font-medium">Test Suites</legend>
            {suites.map((suite, index) => (
              <div
                key={index}
                className="flex flex-col gap-2 border border-neutral-200 p-3 dark:border-neutral-800"
              >
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={suite.provider}
                    onChange={(e) =>
                      updateSuite(index, { provider: e.target.value })
                    }
                    className="border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                  <input
                    placeholder="Suite ID"
                    value={suite.suite_id}
                    onChange={(e) =>
                      updateSuite(index, { suite_id: e.target.value })
                    }
                    className="border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
                  />
                  <input
                    placeholder="Display name"
                    value={suite.display_name}
                    onChange={(e) =>
                      updateSuite(index, { display_name: e.target.value })
                    }
                    className="border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
                  />
                  <input
                    placeholder="Version (optional)"
                    value={suite.version}
                    onChange={(e) =>
                      updateSuite(index, { version: e.target.value })
                    }
                    className="border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
                  />
                </div>

                {suite.provider === "openid" && (
                  <div className="flex flex-col gap-2 border-t border-neutral-200 pt-2 dark:border-neutral-800">
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">
                      OpenID Foundation Conformance Suite configuration. The
                      plan name and configuration must be real values for
                      your own Conformance Suite instance — nothing here is
                      invented automatically.
                    </p>
                    <input
                      placeholder="Plan name (required, e.g. oidcc-basic-certification-test-plan)"
                      value={suite.openidPlanName}
                      onChange={(e) =>
                        updateSuite(index, { openidPlanName: e.target.value })
                      }
                      className="border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
                    />
                    <textarea
                      placeholder='Plan configuration JSON (optional), e.g. {"alias": "my-test"}'
                      value={suite.openidPlanConfiguration}
                      onChange={(e) =>
                        updateSuite(index, {
                          openidPlanConfiguration: e.target.value,
                        })
                      }
                      rows={2}
                      className="border border-neutral-300 bg-transparent px-2 py-1.5 font-mono text-xs dark:border-neutral-700"
                    />
                    <textarea
                      placeholder="Variant JSON (optional)"
                      value={suite.openidVariant}
                      onChange={(e) =>
                        updateSuite(index, { openidVariant: e.target.value })
                      }
                      rows={2}
                      className="border border-neutral-300 bg-transparent px-2 py-1.5 font-mono text-xs dark:border-neutral-700"
                    />
                    <input
                      placeholder="Module names, comma-separated (optional — resolved from the plan if omitted)"
                      value={suite.openidModules}
                      onChange={(e) =>
                        updateSuite(index, { openidModules: e.target.value })
                      }
                      className="border border-neutral-300 bg-transparent px-2 py-1.5 text-sm dark:border-neutral-700"
                    />
                  </div>
                )}

                {suites.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeSuite(index)}
                    className="self-start text-xs text-red-600 hover:underline dark:text-red-400"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={addSuite}
              className="self-start border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700"
            >
              Add test suite
            </button>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              &ldquo;Local mock&rdquo; runs a deterministic local check for
              demo/testing. &ldquo;OpenID Foundation Conformance
              Suite&rdquo; drives a real Conformance Suite instance
              (configured via OPENID_CONFORMANCE_BASE_URL on the backend) —
              supply your own real plan name/configuration. MOSIP/Inji API
              Test-Rig identifiers are introduced in a later milestone.
            </p>
          </fieldset>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1">
              <label htmlFor="min_pass_rate" className="text-sm font-medium">
                Minimum Pass Rate (%)
              </label>
              <input
                id="min_pass_rate"
                type="number"
                min={0}
                max={100}
                value={minPassRate}
                onChange={(e) => setMinPassRate(e.target.value)}
                className="border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label
                htmlFor="critical_failures"
                className="text-sm font-medium"
              >
                Critical Failures Allowed
              </label>
              <input
                id="critical_failures"
                type="number"
                min={0}
                step={1}
                value={criticalFailures}
                onChange={(e) => setCriticalFailures(e.target.value)}
                className="border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="notes" className="text-sm font-medium">
              Notes
            </label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
            />
          </div>

          {fieldErrors.length > 0 && (
            <ul className="border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              {fieldErrors.map((err) => (
                <li key={err}>{err}</li>
              ))}
            </ul>
          )}

          {submitError && (
            <div className="border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              {submitError}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="self-start border border-neutral-800 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-neutral-200"
          >
            {submitting ? "Saving..." : "Create Test Run"}
          </button>
        </form>
      </main>
    </>
  );
}
