"use client";

import React from "react";
import { AlertCircle, Inbox, Lock } from "lucide-react";
import { Button } from "./Button";
import { Skeleton } from "./Skeleton";
import { cn } from "@/lib/utils";

interface LoadingStateProps {
  message?: string;
  className?: string;
  rows?: number;
}

/** Skeleton lines while data loads. The message is announced to screen readers only. */
export const LoadingState: React.FC<LoadingStateProps> = ({
  message = "Loading…",
  className = "",
  rows = 5,
}) => (
  <div className={cn("space-y-3 py-2", className)} role="status" aria-live="polite">
    <span className="sr-only">{message}</span>
    {Array.from({ length: rows }).map((_, i) => (
      <Skeleton key={i} className="h-9" style={{ opacity: 1 - i * 0.12 }} />
    ))}
  </div>
);

interface PanelProps {
  className?: string;
  children: React.ReactNode;
}

const Panel: React.FC<PanelProps> = ({ className, children }) => (
  <div
    className={cn(
      "flex flex-col items-center justify-center rounded-card border border-border bg-surface px-6 py-14 text-center",
      className
    )}
  >
    {children}
  </div>
);

interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = "Nothing here yet",
  description = "No records match these filters.",
  icon: Icon = Inbox,
  actionLabel,
  onAction,
  className = "",
}) => (
  <Panel className={className}>
    <Icon className="mb-3 h-5 w-5 text-fg-tertiary" strokeWidth={1.5} />
    <h3 className="text-sm font-semibold text-fg">{title}</h3>
    <p className="mt-1 max-w-sm text-sm text-fg-secondary">{description}</p>
    {actionLabel && onAction && (
      <Button size="md" className="mt-4" onClick={onAction}>
        {actionLabel}
      </Button>
    )}
  </Panel>
);

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = "Couldn't load this data",
  message = "The request failed. Check your connection and try again.",
  onRetry,
  className = "",
}) => (
  <Panel className={className}>
    <AlertCircle className="mb-3 h-5 w-5 text-danger" strokeWidth={1.5} />
    <h3 className="text-sm font-semibold text-fg">{title}</h3>
    <p className="mt-1 max-w-md text-sm text-fg-secondary">{message}</p>
    {onRetry && (
      <Button variant="secondary" className="mt-4" onClick={onRetry}>
        Try again
      </Button>
    )}
  </Panel>
);

interface UnavailableStateProps {
  title: string;
  description: string;
  className?: string;
}

/** No-permission / unavailable state, e.g. a client opening an admin-only page. */
export const UnavailableState: React.FC<UnavailableStateProps> = ({ title, description, className = "" }) => (
  <Panel className={className}>
    <Lock className="mb-3 h-5 w-5 text-fg-tertiary" strokeWidth={1.5} />
    <h3 className="text-sm font-semibold text-fg">{title}</h3>
    <p className="mt-1 max-w-md text-sm text-fg-secondary">{description}</p>
  </Panel>
);
