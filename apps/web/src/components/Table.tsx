import React from "react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/Skeleton";

/** Bordered scroll container: horizontal scroll on narrow screens, sticky header inside it. */
export const TableContainer: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={cn("overflow-auto rounded-card border border-border bg-surface", className)} {...props} />
);

export const Table: React.FC<React.TableHTMLAttributes<HTMLTableElement>> = ({ className, ...props }) => (
  <table className={cn("w-full border-separate border-spacing-0 text-sm", className)} {...props} />
);

interface ThProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  /** Pin to the left edge while scrolling horizontally. `left` is a CSS length. */
  stickyLeft?: string;
}

export const Th: React.FC<ThProps> = ({ className, stickyLeft, style, ...props }) => (
  <th
    className={cn(
      "sticky top-0 z-20 h-9 whitespace-nowrap border-b border-border bg-surface-subtle px-3 text-left text-xs font-medium text-fg-secondary",
      stickyLeft !== undefined && "z-30",
      className
    )}
    style={stickyLeft !== undefined ? { left: stickyLeft, ...style } : style}
    {...props}
  />
);

interface TdProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  stickyLeft?: string;
  compact?: boolean;
}

/** Row height comes from the cell: 44px by default, 36px when compact. */
export const Td: React.FC<TdProps> = ({ className, stickyLeft, compact, style, ...props }) => (
  <td
    className={cn(
      "border-b border-border px-3 align-middle transition-colors duration-fast group-last:border-b-0",
      compact ? "h-row-compact" : "h-row",
      stickyLeft !== undefined && "sticky z-10 bg-inherit",
      className
    )}
    style={stickyLeft !== undefined ? { left: stickyLeft, ...style } : style}
    {...props}
  />
);

interface TableSkeletonProps {
  /** One width class per column, so the skeleton matches the real layout. */
  columns: string[];
  rows?: number;
  compact?: boolean;
}

export const TableSkeletonRows: React.FC<TableSkeletonProps> = ({ columns, rows = 8, compact }) => (
  <>
    {Array.from({ length: rows }).map((_, rowIndex) => (
      <tr key={rowIndex} className="group bg-surface">
        {columns.map((width, colIndex) => (
          <Td key={colIndex} compact={compact}>
            <Skeleton className={cn("h-4", width)} />
          </Td>
        ))}
      </tr>
    ))}
  </>
);
