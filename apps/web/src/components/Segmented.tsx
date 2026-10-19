"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedProps<T extends string> {
  value: T;
  onValueChange: (value: T) => void;
  options: SegmentedOption<T>[];
  "aria-label": string;
  size?: "sm" | "md";
  className?: string;
}

/** Small two-to-four option switch, e.g. "Match any / Match all". */
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  size = "md",
  className,
  ...rest
}: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={rest["aria-label"]}
      className={cn("inline-flex items-center gap-0.5 rounded-control border border-border bg-surface-subtle p-0.5", className)}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onValueChange(option.value)}
            className={cn(
              "focus-ring whitespace-nowrap rounded-control font-medium transition-colors duration-fast",
              size === "sm" ? "h-6 px-2 text-xs" : "h-7 px-3 text-caption",
              active ? "bg-surface text-fg" : "text-fg-secondary hover:text-fg"
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
