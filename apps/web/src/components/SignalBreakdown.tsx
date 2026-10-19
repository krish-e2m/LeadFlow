import React from "react";
import { ExternalLink } from "lucide-react";
import { SignalDetailItem } from "@/types";
import { StatusBadge } from "@/components/Badge";
import { Tooltip } from "@/components/Tooltip";
import { cn } from "@/lib/utils";

interface SignalBreakdownProps {
  signals: Record<string, SignalDetailItem | unknown>;
  /** Hides weight, provider and source links (used inside the lead sheet). */
  compact?: boolean;
}

export const SignalBreakdown: React.FC<SignalBreakdownProps> = ({ signals, compact = false }) => {
  const metadata = (signals["_metadata"] ?? {}) as { available_signals_ratio?: string; fired_signals_count?: number };
  const signalList = Object.entries(signals).filter(([key]) => !key.startsWith("_")) as [string, SignalDetailItem][];
  const websiteSignals = signalList.filter(([, s]) => s && s.category === "website");
  const marketingSignals = signalList.filter(([, s]) => s && s.category === "marketing");

  const renderSection = (title: string, items: [string, SignalDetailItem][]) => (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-fg">
        {title} <span className="font-normal text-fg-tertiary">({items.length})</span>
      </h3>
      <ul className="divide-y divide-border rounded-card border border-border bg-surface">
        {items.map(([key, item]) => {
          const unavailable = !item.is_available || item.value === null;
          const fired = !unavailable && (item.value ?? 0) >= 0.5;
          return (
            <li key={key} className="space-y-1.5 px-3 py-2.5">
              <div className="flex items-center justify-between gap-3">
                <span className={cn("truncate text-sm", unavailable ? "text-fg-tertiary" : "text-fg")}>{item.label}</span>
                <StatusBadge tone={fired ? "accent" : "neutral"}>
                  {unavailable ? "Unavailable" : fired ? "Detected" : "Not detected"}
                </StatusBadge>
              </div>

              {!compact && (
                <div className="flex flex-wrap items-center gap-x-3 text-xs text-fg-tertiary">
                  <span>Weight {item.weight}×</span>
                  {item.provider && <span className="font-mono">via {item.provider}</span>}
                  {item.source_url && (
                    <a
                      href={item.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="focus-ring inline-flex items-center gap-1 rounded-control text-accent hover:text-accent-hover"
                    >
                      Source <ExternalLink className="h-3 w-3" strokeWidth={1.5} />
                    </a>
                  )}
                </div>
              )}

              {item.evidence && (
                <Tooltip content={item.evidence}>
                  <p className={cn("text-caption text-fg-secondary", compact && "line-clamp-2")}>{item.evidence}</p>
                </Tooltip>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );

  return (
    <div className="space-y-6">
      {metadata.available_signals_ratio && (
        <p className="text-caption text-fg-secondary">
          <span className="font-medium text-fg">{metadata.available_signals_ratio}</span> signals evaluated,{" "}
          {metadata.fired_signals_count ?? 0} detected. Unavailable signals are skipped, not scored as zero.
        </p>
      )}
      {renderSection("Website signals", websiteSignals)}
      {renderSection("Marketing signals", marketingSignals)}
    </div>
  );
};
