import React from "react";
import { cn } from "@/lib/utils";

interface MeterBarProps {
  /** 0–100. Null renders an empty track. */
  value: number | null;
  /** Accent fill when true, neutral otherwise (e.g. qualified scores, quotas that are nearly used). */
  strong?: boolean;
  /** Danger fill, for a quota that is exhausted or a failed run. */
  danger?: boolean;
  className?: string;
  label?: string;
}

/** Thin 4px progress bar: neutral by default, accent when strong. */
export const MeterBar: React.FC<MeterBarProps> = ({ value, strong = false, danger = false, className, label }) => {
  const width = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div
      className={cn("h-1 w-full overflow-hidden rounded-full bg-surface-muted", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(width)}
      aria-label={label}
    >
      <div
        className={cn(
          // The app-wide prefers-reduced-motion rule in globals.css already collapses this to
          // 1ms, so no separate motion-reduce override is needed here.
          "h-full rounded-full transition-[width] duration-500 ease-out",
          danger ? "bg-danger" : strong ? "bg-accent" : "bg-fg-tertiary"
        )}
        style={{ width: `${width}%` }}
      />
    </div>
  );
};

/** Section with a 14px/600 heading and optional one-line description. */
export const Section: React.FC<{
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, description, actions, children }) => (
  <section className="space-y-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        {description && <p className="mt-0.5 text-caption text-fg-secondary">{description}</p>}
      </div>
      {actions}
    </div>
    {children}
  </section>
);
