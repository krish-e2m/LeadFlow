import React from "react";
import { Logo } from "@/components/Brand";
import { cn } from "@/lib/utils";

interface AuthShellProps {
  title: string;
  description?: string;
  /** "narrow" is the 400px sign-in card; "wide" fits the access request form. */
  width?: "narrow" | "wide";
  children: React.ReactNode;
  footer?: React.ReactNode;
}

/** Centered card over a subtle gradient backdrop (the same treatment as the marketing landing
 * page): wordmark, title, one form. No illustrations, no split screen. */
export const AuthShell: React.FC<AuthShellProps> = ({ title, description, width = "narrow", children, footer }) => (
  <main className="landing-mesh-bg relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4 py-10">
    <div aria-hidden className="landing-grid-pattern pointer-events-none absolute inset-0 opacity-30" />
    <div className={cn("relative w-full", width === "narrow" ? "max-w-[400px]" : "max-w-lg")}>
      <div className="mb-6 flex justify-center">
        <Logo />
      </div>
      <div className="rounded-card border border-border bg-surface p-6 shadow-pop sm:p-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-fg">{title}</h1>
          {description && <p className="mt-1 text-sm text-fg-secondary">{description}</p>}
        </div>
        {children}
      </div>
      {footer && <div className="mt-5 text-center text-caption text-fg-secondary">{footer}</div>}
    </div>
  </main>
);

/** Inline error shown above a form. */
export const FormError: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p role="alert" className="mb-4 rounded-control bg-danger-subtle px-3 py-2.5 text-caption text-danger">
    {children}
  </p>
);

/** Text link in the accent color, for use inside sentences. */
export const textLinkClass =
  "focus-ring rounded-control font-medium text-accent transition-colors duration-fast hover:text-accent-hover";
