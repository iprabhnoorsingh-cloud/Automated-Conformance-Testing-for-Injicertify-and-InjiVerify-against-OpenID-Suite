const COLORS: Record<string, string> = {
  CONFIGURED: "bg-neutral-400",
  QUEUED: "bg-amber-500",
  RUNNING: "bg-blue-500",
  PASSED: "bg-green-500",
  FAILED: "bg-red-500",
  CANCELLED: "bg-neutral-500",
};

export function StatusBadge({ status }: { status: string }) {
  const color = COLORS[status] ?? "bg-neutral-400";
  return (
    <span className="inline-flex items-center gap-1.5 border border-neutral-200 px-2 py-0.5 text-xs font-medium dark:border-neutral-800">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {status}
    </span>
  );
}
