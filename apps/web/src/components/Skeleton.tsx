import React from "react";
import { cn } from "@/lib/utils";

/** Loading placeholder with a gentle opacity pulse (no shimmer). */
export const Skeleton: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={cn("skeleton h-4 w-full", className)} aria-hidden="true" {...props} />
);
