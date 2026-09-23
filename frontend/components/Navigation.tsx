import Link from "next/link";

export function Navigation() {
  return (
    <header className="border-b border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <span className="font-mono text-sm font-semibold tracking-tight">
          MOSIP Conformance Center
        </span>
        <nav className="flex gap-6 text-sm text-neutral-500 dark:text-neutral-400">
          <span className="cursor-not-allowed" title="Not implemented in this milestone">
            Dashboard
          </span>
          <Link
            href="/test-runs"
            className="hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            Test Runs
          </Link>
          <span className="cursor-not-allowed" title="Not implemented in this milestone">
            Environments
          </span>
          <span className="cursor-not-allowed" title="Not implemented in this milestone">
            Reports
          </span>
        </nav>
      </div>
    </header>
  );
}
