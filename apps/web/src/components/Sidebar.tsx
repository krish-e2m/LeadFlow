"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "motion/react";
import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { Avatar, Logo } from "@/components/Brand";
import { Badge } from "@/components/Badge";
import { Skeleton } from "@/components/Skeleton";
import { Tooltip } from "@/components/Tooltip";
import { isActivePath, visibleGroups } from "@/components/navigation";

interface SidebarProps {
  /** Icon-rail mode (64px). Only applies on desktop. */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  /** Called after a link is chosen, e.g. to close the mobile drawer. */
  onNavigate?: () => void;
  /** Unique id so the sliding active bar never animates between the desktop and drawer instances. */
  indicatorId: string;
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed = false, onToggleCollapsed, onNavigate, indicatorId }) => {
  const pathname = usePathname();
  const { user, isLoading, logout } = useAuth();
  const profilePending = isLoading && !user;

  const role = user?.role ?? "client_viewer";
  const isAdmin = role !== "client_viewer";
  const groups = visibleGroups(role);
  const workspace = user?.org_name || (role === "super_admin" ? "All organizations" : "Workspace");

  return (
    // Translucent, not flat: the gradient painted on AppShell's root shows faintly through, the
    // same way the landing header sits as bg-white/85 + blur over its own hero gradient.
    <div className="flex h-full flex-col bg-surface-subtle/90 backdrop-blur-md">
      {/* Workspace */}
      <div className={cn("flex h-topbar shrink-0 items-center gap-2 border-b border-border", collapsed ? "justify-center px-0" : "px-4")}>
        <Logo showName={false} />
        {!collapsed && (
          <>
            {profilePending ? (
              <Skeleton className="h-4 w-28 flex-1" />
            ) : (
              <span className="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{workspace}</span>
            )}
            {isAdmin && <Badge size="sm">Admin</Badge>}
          </>
        )}
      </div>

      {/* Navigation */}
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
        {profilePending && (
          <div className="space-y-2" role="status" aria-live="polite">
            <span className="sr-only">Loading navigation…</span>
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        )}
        {!profilePending && groups.map((group, groupIndex) => (
          <div key={group.label} className={cn(groupIndex > 0 && "mt-5")}>
            {collapsed ? (
              groupIndex > 0 && <div className="mx-2 mb-3 h-px bg-border" />
            ) : (
              <p className="mb-1.5 px-3 text-xs font-medium uppercase tracking-label text-fg-tertiary">{group.label}</p>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActivePath(pathname, item.href);
                const Icon = item.icon;
                const link = (
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "focus-ring relative flex h-9 items-center gap-3 rounded-control text-sm font-medium transition-colors duration-fast",
                      collapsed ? "justify-center px-0" : "px-3",
                      active ? "bg-surface text-fg" : "text-fg-secondary hover:bg-surface-muted hover:text-fg"
                    )}
                  >
                    {active && (
                      <motion.span
                        layoutId={`nav-active-${indicatorId}`}
                        className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent"
                        transition={{ type: "spring", bounce: 0, duration: 0.25 }}
                      />
                    )}
                    <Icon
                      className={cn("h-5 w-5 shrink-0", active ? "text-accent" : "text-fg-tertiary")}
                      strokeWidth={1.5}
                      aria-hidden="true"
                    />
                    {collapsed ? <span className="sr-only">{item.name}</span> : <span className="truncate">{item.name}</span>}
                  </Link>
                );
                return (
                  <li key={item.href}>
                    {collapsed ? (
                      <Tooltip content={item.name} side="right">
                        {link}
                      </Tooltip>
                    ) : (
                      link
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* User profile & explicit Sign out button */}
      <div className="shrink-0 border-t border-border p-2 sm:p-2.5">
        {collapsed ? (
          <div className="flex flex-col items-center gap-1.5">
            <Tooltip content={user?.full_name || user?.email || "Account"} side="right">
              <div className="flex h-8 w-8 items-center justify-center">
                <Avatar name={user?.full_name || user?.email || "Account"} src={user?.avatar_url} size="sm" />
              </div>
            </Tooltip>
            <Tooltip content="Sign out" side="right">
              <button
                type="button"
                onClick={() => void logout()}
                aria-label="Sign out"
                className="focus-ring flex h-8 w-8 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-danger-subtle hover:text-danger"
              >
                <LogOut className="h-4 w-4" strokeWidth={1.5} />
              </button>
            </Tooltip>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 rounded-control p-1.5 transition-colors duration-fast hover:bg-surface-muted/60">
            <div className="flex min-w-0 items-center gap-2.5">
              <Avatar name={user?.full_name || user?.email || "Account"} src={user?.avatar_url} size="sm" />
              <div className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-fg">
                  {user?.full_name || user?.email?.split("@")[0] || "User"}
                </span>
                <span className="block truncate text-[11px] text-fg-tertiary">
                  {user?.email || role}
                </span>
              </div>
            </div>
            <Tooltip content="Sign out" side="top">
              <button
                type="button"
                onClick={() => void logout()}
                aria-label="Sign out"
                className="focus-ring flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-danger-subtle hover:text-danger"
              >
                <LogOut className="h-3.5 w-3.5" strokeWidth={1.5} />
              </button>
            </Tooltip>
          </div>
        )}
      </div>

      {/* Collapse toggle (desktop only) */}
      {onToggleCollapsed && (
        <div className={cn("hidden shrink-0 border-t border-border/60 p-2 lg:block", collapsed && "flex justify-center")}>
          <Tooltip content={collapsed ? "Expand sidebar" : "Collapse sidebar"} side="right">
            <button
              type="button"
              onClick={onToggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className={cn(
                "focus-ring flex h-8 items-center gap-2 rounded-control text-caption text-fg-secondary transition-colors duration-fast hover:bg-surface-muted hover:text-fg",
                collapsed ? "w-8 justify-center" : "w-full px-2"
              )}
            >
              {collapsed ? (
                <PanelLeftOpen className="h-4 w-4" strokeWidth={1.5} />
              ) : (
                <>
                  <PanelLeftClose className="h-4 w-4" strokeWidth={1.5} />
                  Collapse
                </>
              )}
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  );
};

