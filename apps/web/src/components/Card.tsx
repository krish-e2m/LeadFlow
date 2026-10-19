import React from "react";
import { cn } from "@/lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Highlights the card with the accent border (selected / current item). */
  glow?: boolean;
  /** Set on cards that are themselves a click target (a KPI tile linking out, a list row): lifts
   * a touch and deepens its shadow on hover. Leave off for plain containers like forms. */
  interactive?: boolean;
}

/** Resting surface: 1px border, 12px radius, a soft shadow (var(--shadow-card)) for a touch of
 * depth even at rest. Bigger floating layers (dropdowns, sheets, modals) use `shadow-pop`/`shadow-modal`. */
export const Card: React.FC<CardProps> = ({ children, className, glow = false, interactive = false, ...props }) => (
  <div
    className={cn(
      "rounded-card border bg-surface p-5 shadow-card",
      glow ? "border-accent" : "border-border",
      interactive &&
        "transition-[transform,box-shadow] duration-base ease-out-expo hover:-translate-y-0.5 hover:shadow-pop",
      className
    )}
    {...props}
  >
    {children}
  </div>
);
