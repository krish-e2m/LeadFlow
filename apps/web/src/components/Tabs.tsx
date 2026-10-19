"use client";

import React, { useId } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

export interface TabItem {
  value: string;
  label: string;
  count?: number;
}

interface TabsProps {
  value: string;
  onValueChange: (value: string) => void;
  items: TabItem[];
  /** Tab panels, rendered with <TabsContent>. Omit when the tabs only drive filters. */
  children?: React.ReactNode;
  className?: string;
}

/** Underline tabs; the accent indicator slides between items. */
export const Tabs: React.FC<TabsProps> = ({ value, onValueChange, items, children, className }) => {
  const indicatorId = useId();
  return (
    <TabsPrimitive.Root value={value} onValueChange={onValueChange} className={className}>
      <TabsPrimitive.List className="flex items-center gap-1 border-b border-border max-sm:overflow-x-auto">
        {items.map((item) => {
          const active = item.value === value;
          return (
            <TabsPrimitive.Trigger
              key={item.value}
              value={item.value}
              className={cn(
                "focus-ring relative inline-flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-t-control px-3 text-sm font-medium",
                "transition-colors duration-fast",
                active ? "text-fg" : "text-fg-secondary hover:text-fg"
              )}
            >
              {item.label}
              {item.count !== undefined && (
                <span className="rounded-control bg-surface-subtle px-1.5 text-xs text-fg-secondary">{item.count}</span>
              )}
              {active && (
                <motion.span
                  layoutId={`tab-indicator-${indicatorId}`}
                  className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent"
                  transition={{ type: "spring", bounce: 0, duration: 0.25 }}
                />
              )}
            </TabsPrimitive.Trigger>
          );
        })}
      </TabsPrimitive.List>
      {children}
    </TabsPrimitive.Root>
  );
};

export const TabsContent = TabsPrimitive.Content;
