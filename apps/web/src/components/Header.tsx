"use client";

import React, { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ChevronRight, LogOut, Menu, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { Avatar } from "@/components/Brand";
import { Badge } from "@/components/Badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/DropdownMenu";
import { breadcrumbFor, roleLabel } from "@/components/navigation";

interface HeaderProps {
  onOpenMenu: () => void;
  onOpenSearch: () => void;
  shortcutLabel: string;
}

export const Header: React.FC<HeaderProps> = ({ onOpenMenu, onOpenSearch, shortcutLabel }) => {
  const pathname = usePathname();
  const { user, logout, isLoading } = useAuth();
  const crumbs = breadcrumbFor(pathname);
  const workspace = user?.org_name || (user?.role === "super_admin" ? "All organizations" : "Workspace");
  const displayName = user?.full_name || user?.email || "Account";

  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        // Translucent + blurred, same as the landing page's own sticky header, so AppShell's
        // gradient canvas reads through it instead of a flat white bar.
        "sticky top-0 z-30 flex h-topbar items-center gap-3 border-b bg-surface/90 px-4 backdrop-blur-md transition-shadow duration-base sm:px-6 lg:px-8",
        scrolled ? "border-border shadow-[0_1px_0_0_rgba(15,23,42,0.04),0_8px_20px_-16px_rgba(15,23,42,0.25)]" : "border-border"
      )}
    >
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="Open navigation"
        className="focus-ring -ml-2 inline-flex h-9 w-9 items-center justify-center rounded-control text-fg-secondary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg lg:hidden"
      >
        <Menu className="h-5 w-5" strokeWidth={1.5} />
      </button>

      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex items-center gap-1.5 text-sm">
          <li className="hidden truncate text-fg-tertiary sm:block">{workspace}</li>
          {crumbs.map((crumb, index) => (
            <React.Fragment key={`${crumb}-${index}`}>
              <li aria-hidden="true" className={index === 0 ? "hidden sm:block" : undefined}>
                <ChevronRight className="h-3.5 w-3.5 text-fg-tertiary" strokeWidth={1.5} />
              </li>
              <li
                className={
                  index === crumbs.length - 1
                    ? "truncate font-medium text-fg"
                    : "hidden truncate text-fg-tertiary sm:block"
                }
                aria-current={index === crumbs.length - 1 ? "page" : undefined}
              >
                {crumb}
              </li>
            </React.Fragment>
          ))}
        </ol>
      </nav>

      <button
        type="button"
        onClick={onOpenSearch}
        className="focus-ring hidden h-control-sm w-64 items-center gap-2 rounded-control border border-border-strong bg-surface px-2.5 text-caption text-fg-tertiary transition-colors duration-fast hover:border-fg-tertiary hover:text-fg-secondary md:inline-flex"
      >
        <Search className="h-4 w-4" strokeWidth={1.5} />
        <span className="flex-1 text-left">Search or jump to…</span>
        <kbd className="rounded-[4px] border border-border bg-surface-subtle px-1.5 font-sans text-xs text-fg-secondary">
          {shortcutLabel}
        </kbd>
      </button>
      <button
        type="button"
        onClick={onOpenSearch}
        aria-label="Search"
        className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-control text-fg-secondary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg md:hidden"
      >
        <Search className="h-5 w-5" strokeWidth={1.5} />
      </button>

      {user?.must_reset_password && (
        <Badge variant="warning" className="hidden sm:inline-flex">
          Password reset required
        </Badge>
      )}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="Account menu"
            className="focus-ring inline-flex items-center gap-2 rounded-full border border-border/70 bg-surface/80 p-0.5 pr-2 transition-all duration-fast hover:border-border-strong hover:bg-surface"
          >
            {isLoading && !user ? (
              <span className="skeleton block h-7 w-7 rounded-full" />
            ) : (
              <Avatar name={displayName} src={user?.avatar_url} size="sm" />
            )}
            <span className="hidden max-w-[120px] truncate text-xs font-medium text-fg sm:inline-block">
              {user?.full_name || displayName}
            </span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuLabel className="space-y-0.5">
            <span className="block truncate text-sm font-medium text-fg">{displayName}</span>
            {user?.full_name && user.email && <span className="block truncate text-xs text-fg-secondary">{user.email}</span>}
            <span className="block text-xs text-fg-tertiary">{roleLabel(user?.role)}</span>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => void logout()} className="text-danger focus:bg-danger-subtle focus:text-danger">
            <LogOut className="h-4 w-4" strokeWidth={1.5} />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Prominent direct Sign out button */}
      <button
        id="header-logout-btn"
        type="button"
        onClick={() => void logout()}
        aria-label="Sign out"
        title="Sign out"
        className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-control border border-border/80 bg-surface px-2.5 text-xs font-medium text-fg-secondary transition-colors duration-fast hover:border-danger/30 hover:bg-danger-subtle hover:text-danger"
      >
        <LogOut className="h-3.5 w-3.5" strokeWidth={1.5} />
        <span className="hidden sm:inline">Sign out</span>
      </button>
    </header>
  );
};
