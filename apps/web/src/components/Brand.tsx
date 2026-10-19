import React from "react";
import { cn, initialsFor } from "@/lib/utils";

/** Wordmark: ink square mark + name. */
export const Logo: React.FC<{ className?: string; showName?: boolean }> = ({ className, showName = true }) => (
  <span className={cn("inline-flex items-center gap-2", className)}>
    <span
      className="inline-flex h-6 w-6 items-center justify-center rounded-control bg-ink text-xs font-semibold text-white"
      aria-hidden="true"
    >
      LF
    </span>
    {showName && <span className="text-sm font-semibold tracking-tight text-fg">LeadFlow</span>}
  </span>
);

interface AvatarProps {
  name: string;
  size?: "sm" | "md";
  src?: string | null;
  className?: string;
}

/** Neutral initials or image avatar. The only pill-shaped element in the system. */
export const Avatar: React.FC<AvatarProps> = ({ name, size = "md", src, className }) => {
  const [imageError, setImageError] = React.useState(false);

  if (src && !imageError) {
    return (
      <img
        src={src}
        alt={name}
        onError={() => setImageError(true)}
        className={cn(
          "inline-flex shrink-0 select-none items-center justify-center rounded-full object-cover",
          size === "sm" ? "h-6 w-6" : "h-8 w-8",
          className
        )}
      />
    );
  }

  return (
    <span
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full bg-surface-muted font-medium text-fg-secondary",
        size === "sm" ? "h-6 w-6 text-xs" : "h-8 w-8 text-caption",
        className
      )}
      aria-hidden="true"
    >
      {initialsFor(name)}
    </span>
  );
};

