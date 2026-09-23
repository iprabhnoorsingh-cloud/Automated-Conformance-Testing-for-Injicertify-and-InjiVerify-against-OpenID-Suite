const NAV_ITEMS = ["Dashboard", "Test Runs", "Environments", "Reports"];

export function Navigation() {
  return (
    <header className="border-b border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <span className="font-mono text-sm font-semibold tracking-tight">
          MOSIP Conformance Center
        </span>
        <nav className="flex gap-6 text-sm text-neutral-500 dark:text-neutral-400">
          {NAV_ITEMS.map((item) => (
            <span
              key={item}
              className="cursor-not-allowed"
              title="Not implemented in this milestone"
            >
              {item}
            </span>
          ))}
        </nav>
      </div>
    </header>
  );
}
