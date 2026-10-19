"use client";

import React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

export const TooltipProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <TooltipPrimitive.Provider delayDuration={300} skipDelayDuration={200}>
    {children}
  </TooltipPrimitive.Provider>
);

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  side?: "top" | "right" | "bottom" | "left";
}

/** Wraps a single focusable element. Used for truncated text, icon-only buttons and exact dates. */
export const Tooltip: React.FC<TooltipProps> = ({ content, children, side = "top" }) => {
  if (!content) return children;
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          style={{ transformOrigin: "var(--radix-tooltip-content-transform-origin)" }}
          className="z-[60] max-w-xs break-words rounded-control bg-ink px-2 py-1 text-xs text-white shadow-pop data-[state=closed]:animate-pop-out data-[state=delayed-open]:animate-pop-in data-[state=instant-open]:animate-pop-in"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
};
