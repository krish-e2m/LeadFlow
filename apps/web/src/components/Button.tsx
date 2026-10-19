import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive" | "danger" | "outline";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary = ink, secondary = white with strong border, ghost = text only, destructive = danger.
   *  "danger" and "outline" are kept as aliases of destructive and secondary for existing screens. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
}

const variants: Record<ButtonVariant, string> = {
  primary: "bg-ink text-white hover:bg-ink-hover active:bg-ink-hover active:scale-[0.98]",
  secondary:
    "bg-surface text-fg border border-border-strong hover:bg-surface-subtle active:bg-surface-muted active:scale-[0.98]",
  outline:
    "bg-surface text-fg border border-border-strong hover:bg-surface-subtle active:bg-surface-muted active:scale-[0.98]",
  ghost: "bg-transparent text-fg-secondary hover:bg-surface-subtle hover:text-fg active:bg-surface-muted",
  destructive: "bg-danger text-white hover:opacity-90 active:opacity-100 active:scale-[0.98]",
  danger: "bg-danger text-white hover:opacity-90 active:opacity-100 active:scale-[0.98]",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-control-sm px-3 text-caption gap-1.5",
  md: "h-control px-3.5 text-sm gap-2",
  lg: "h-control-lg px-4 text-sm gap-2",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { children, className, variant = "primary", size = "md", isLoading = false, disabled, type = "button", ...props },
    ref
  ) => {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "focus-ring inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-control font-medium",
          "transition-[background-color,color,border-color,opacity,transform] duration-fast",
          "disabled:pointer-events-none disabled:opacity-50",
          variants[variant],
          sizes[size],
          className
        )}
        disabled={disabled || isLoading}
        aria-busy={isLoading || undefined}
        {...props}
      >
        {isLoading && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.5} aria-hidden="true" />}
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
