import { API_URL } from "@/lib/config";

export type Environment = "development" | "staging" | "production";

export const ENVIRONMENTS: Environment[] = [
  "development",
  "staging",
  "production",
];

export type TestRunStatus =
  | "CONFIGURED"
  | "QUEUED"
  | "RUNNING"
  | "PASSED"
  | "FAILED"
  | "CANCELLED";

export type ExecutionStatus =
  | "QUEUED"
  | "RUNNING"
  | "PASSED"
  | "FAILED"
  | "CANCELLED";

/**
 * Selectable components. Mirrors backend/app/components.py — there is no
 * catalog endpoint yet, so this list must be kept in sync by hand.
 */
export const COMPONENTS: Record<string, string> = {
  "inji-certify": "Inji Certify",
  "inji-verify": "Inji Verify",
};

export interface TestSuiteConfig {
  provider: string;
  suite_id: string;
  display_name: string;
  version?: string | null;
}

export interface BenchmarkConfig {
  minimum_pass_rate: number;
  critical_failures_allowed: number;
}

export interface MetadataConfig {
  notes?: string | null;
  created_by?: string | null;
}

export interface TestRun {
  id: string;
  run_name: string;
  environment: Environment;
  components: string[];
  test_suites: TestSuiteConfig[];
  benchmark: BenchmarkConfig;
  metadata?: MetadataConfig | null;
  status: TestRunStatus;
  created_at: string;
}

export interface TestRunCreateInput {
  run_name: string;
  environment: Environment;
  components: string[];
  test_suites: TestSuiteConfig[];
  benchmark: BenchmarkConfig;
  metadata?: MetadataConfig | null;
}

export interface Step {
  step_id: string;
  display_name: string;
  provider: string;
  component: string;
  order: number;
  status: ExecutionStatus;
}

export interface StepResult {
  step_id: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at?: string | null;
  message: string;
  details?: Record<string, unknown> | null;
}

export interface Execution {
  id: string;
  test_run_id: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at?: string | null;
  current_step?: string | null;
  total_steps: number;
  completed_steps: number;
  steps: Step[];
  step_results: StepResult[];
}

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const field = Array.isArray(d?.loc) ? d.loc.join(".") : "";
          return field ? `${field}: ${d?.msg}` : d?.msg;
        })
        .filter(Boolean)
        .join("; ");
    }
    return `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      "Could not reach the backend. Confirm it's running and NEXT_PUBLIC_API_URL is correct.",
    );
  }

  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listTestRuns(): Promise<TestRun[]> {
  return request<TestRun[]>("/api/test-runs");
}

export function getTestRun(id: string): Promise<TestRun> {
  return request<TestRun>(`/api/test-runs/${id}`);
}

export function createTestRun(input: TestRunCreateInput): Promise<TestRun> {
  return request<TestRun>("/api/test-runs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteTestRun(id: string): Promise<void> {
  return request<void>(`/api/test-runs/${id}`, { method: "DELETE" });
}

export function executeTestRun(id: string): Promise<Execution> {
  return request<Execution>(`/api/test-runs/${id}/execute`, {
    method: "POST",
  });
}

export async function getLatestExecution(
  id: string,
): Promise<Execution | null> {
  try {
    return await request<Execution>(`/api/test-runs/${id}/execution`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}
