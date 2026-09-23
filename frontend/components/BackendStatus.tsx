"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/config";

type Status = "checking" | "connected" | "unavailable";

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_URL}/health`)
      .then((res) => {
        if (!cancelled) setStatus(res.ok ? "connected" : "unavailable");
      })
      .catch(() => {
        if (!cancelled) setStatus("unavailable");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const color =
    status === "connected"
      ? "bg-green-500"
      : status === "unavailable"
        ? "bg-red-500"
        : "bg-neutral-400";

  const label =
    status === "connected"
      ? "Connected"
      : status === "unavailable"
        ? "Unavailable"
        : "Checking...";

  return (
    <div className="flex items-center justify-between border border-neutral-200 px-4 py-3 text-sm dark:border-neutral-800">
      <span className="font-medium">Backend</span>
      <span className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${color}`} />
        {label}
      </span>
    </div>
  );
}
