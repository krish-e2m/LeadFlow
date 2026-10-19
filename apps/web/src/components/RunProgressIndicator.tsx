import React from "react";
import { Run } from "@/types";
import { StatusBadge } from "@/components/Badge";
import { MeterBar } from "@/components/Meter";
import type { Tone } from "@/lib/utils";

interface RunProgressIndicatorProps {
  run: Run;
}

const statusTone: Record<Run["status"], Tone> = {
  completed: "success",
  running: "accent",
  failed: "danger",
  pending: "warning",
};

export const RunProgressIndicator: React.FC<RunProgressIndicatorProps> = ({ run }) => {
  const metrics = [
    { label: "Total", value: run.items_total },
    { label: "Processed", value: run.items_processed },
    { label: "Succeeded", value: run.items_succeeded },
    { label: "Failed", value: run.items_failed },
  ];

  return (
    <div className="space-y-4 rounded-card border border-border bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <StatusBadge tone={statusTone[run.status] ?? "neutral"}>{run.status}</StatusBadge>
          <span className="truncate text-sm font-medium capitalize text-fg">{run.run_type} run</span>
        </div>
        <span className="text-sm font-medium text-fg">{run.progress_pct}%</span>
      </div>

      <MeterBar value={run.progress_pct} strong={run.status !== "failed"} danger={run.status === "failed"} label="Run progress" />

      <dl className="grid grid-cols-4 gap-3 border-t border-border pt-3">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt className="text-xs text-fg-secondary">{metric.label}</dt>
            <dd className="text-sm font-semibold text-fg">{metric.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
};
