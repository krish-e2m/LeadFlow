"use client";

import React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  /** Accessible name when there is no visible label. */
  "aria-label"?: string;
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  className?: string;
}

const heights = { sm: "h-control-sm", md: "h-control", lg: "h-control-lg" } as const;

export const Select: React.FC<SelectProps> = ({
  value,
  onValueChange,
  options,
  placeholder,
  size = "md",
  disabled,
  className,
  ...rest
}) => (
  <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
    <SelectPrimitive.Trigger
      aria-label={rest["aria-label"]}
      className={cn(
        "focus-ring inline-flex w-full items-center justify-between gap-2 rounded-control border border-border-strong bg-surface px-3 text-sm text-fg",
        "transition-[border-color,background-color] duration-fast hover:border-fg-tertiary data-[state=open]:border-fg-tertiary",
        "data-[placeholder]:text-fg-tertiary disabled:cursor-not-allowed disabled:opacity-60",
        heights[size],
        className
      )}
    >
      <span className="truncate">
        <SelectPrimitive.Value placeholder={placeholder} />
      </span>
      <SelectPrimitive.Icon>
        <ChevronDown className="h-4 w-4 text-fg-tertiary" strokeWidth={1.5} />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position="popper"
        sideOffset={4}
        style={{ transformOrigin: "var(--radix-select-content-transform-origin)" }}
        className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-card border border-border bg-surface p-1 shadow-pop data-[state=closed]:animate-pop-out data-[state=open]:animate-pop-in"
      >
        <SelectPrimitive.Viewport>
          {options.map((option) => (
            <SelectPrimitive.Item
              key={option.value}
              value={option.value}
              className="relative flex h-8 cursor-pointer select-none items-center rounded-control pl-8 pr-3 text-sm text-fg outline-none data-[highlighted]:bg-surface-subtle data-[state=checked]:font-medium"
            >
              <SelectPrimitive.ItemIndicator className="absolute left-2.5">
                <Check className="h-4 w-4 text-accent" strokeWidth={1.5} />
              </SelectPrimitive.ItemIndicator>
              <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
            </SelectPrimitive.Item>
          ))}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  </SelectPrimitive.Root>
);
