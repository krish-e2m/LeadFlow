import React from "react";
import { cn, type Tone } from "@/lib/utils";

type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: "sm" | "md";
  className?: string;
}

const variants: Record<BadgeVariant, string> = {
  success: "bg-success-subtle text-success",
  warning: "bg-warning-subtle text-warning",
  danger: "bg-danger-subtle text-danger",
  info: "bg-accent-subtle text-accent",
  neutral: "bg-neutral-subtle text-neutral",
};

/** Quiet tinted label for counts and short metadata. For states, prefer StatusBadge (dot + label). */
export const Badge: React.FC<BadgeProps> = ({ children, variant = "neutral", size = "md", className }) => (
  <span
    className={cn(
      "inline-flex select-none items-center whitespace-nowrap rounded-control font-medium capitalize",
      size === "sm" ? "h-5 px-1.5 text-xs" : "h-6 px-2 text-caption",
      variants[variant],
      className
    )}
  >
    {children}
  </span>
);

const dotColor: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  accent: "bg-accent",
  neutral: "bg-fg-tertiary",
};

interface StatusBadgeProps {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}

/** Small dot + label. Never a loud filled pill. Used for verification, score band, stage and approval. */
export const StatusBadge: React.FC<StatusBadgeProps> = ({ tone = "neutral", children, className }) => (
  <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-caption font-medium text-fg", className)}>
    <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotColor[tone])} aria-hidden="true" />
    <span className="capitalize">{children}</span>
  </span>
);
