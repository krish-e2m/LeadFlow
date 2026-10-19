"use client";

import React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

type CheckboxProps = Omit<React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>, "children">;

export const Checkbox = React.forwardRef<React.ElementRef<typeof CheckboxPrimitive.Root>, CheckboxProps>(
  ({ className, ...props }, ref) => (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        "focus-ring peer inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] border border-border-strong bg-surface",
        "transition-[background-color,border-color] duration-fast hover:border-fg-tertiary",
        "data-[state=checked]:border-ink data-[state=checked]:bg-ink data-[state=indeterminate]:border-ink data-[state=indeterminate]:bg-ink",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="text-white">
        {props.checked === "indeterminate" ? (
          <Minus className="h-3 w-3" strokeWidth={2} />
        ) : (
          <Check className="h-3 w-3" strokeWidth={2} />
        )}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
);
Checkbox.displayName = "Checkbox";
