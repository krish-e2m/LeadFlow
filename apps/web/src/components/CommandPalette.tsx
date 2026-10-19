"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { CornerDownLeft, LogOut, Search } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { visibleGroups } from "@/components/navigation";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;
const EASE_IN = [0.4, 0, 1, 1] as const;

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const itemClass =
  "flex h-9 cursor-pointer select-none items-center gap-3 rounded-control px-3 text-sm text-fg-secondary " +
  "data-[selected=true]:bg-surface-subtle data-[selected=true]:text-fg";

/** ⌘K palette: jump to any screen you can access, or search leads by name or domain. */
export const CommandPalette: React.FC<CommandPaletteProps> = ({ open, onOpenChange }) => {
  const router = useRouter();
  const { user, logout } = useAuth();
  const reduceMotion = useReducedMotion();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const groups = visibleGroups(user?.role ?? "client_viewer");
  const trimmed = query.trim();

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-50"
                style={{ background: "var(--backdrop)" }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1, transition: { duration: 0.18, ease: EASE_OUT } }}
                exit={{ opacity: 0, transition: { duration: 0.12, ease: EASE_IN } }}
              />
            </Dialog.Overlay>
            <div className="pointer-events-none fixed inset-0 z-50 flex items-start justify-center px-4 pt-[15vh]">
              <Dialog.Content asChild forceMount aria-describedby={undefined}>
                <motion.div
                  className="pointer-events-auto w-full max-w-xl overflow-hidden rounded-sheet border border-border bg-surface shadow-modal"
                  initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.97, y: reduceMotion ? 0 : -8 }}
                  animate={{ opacity: 1, scale: 1, y: 0, transition: { duration: 0.2, ease: EASE_OUT } }}
                  exit={{ opacity: 0, scale: reduceMotion ? 1 : 0.97, transition: { duration: 0.14, ease: EASE_IN } }}
                >
                  <Dialog.Title className="sr-only">Command palette</Dialog.Title>
                  <Command label="Command palette" loop>
                    <div className="flex items-center gap-3 border-b border-border px-4">
                      <Search className="h-4 w-4 shrink-0 text-fg-tertiary" strokeWidth={1.5} />
                      <Command.Input
                        value={query}
                        onValueChange={setQuery}
                        placeholder="Search leads or jump to a page…"
                        className="h-12 w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-tertiary"
                      />
                    </div>
                    <Command.List className="max-h-80 overflow-y-auto p-2">
                      {!trimmed && (
                        <Command.Empty className="px-3 py-8 text-center text-sm text-fg-secondary">
                          No matching pages.
                        </Command.Empty>
                      )}

                      {trimmed && (
                        <Command.Group
                          forceMount
                          heading="Leads"
                          className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-label [&_[cmdk-group-heading]]:text-fg-tertiary"
                        >
                          <Command.Item
                            forceMount
                            value={`search-leads ${trimmed}`}
                            onSelect={() => go(`/leads?q=${encodeURIComponent(trimmed)}`)}
                            className={itemClass}
                          >
                            <Search className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                            <span className="min-w-0 flex-1 truncate">Search leads for “{trimmed}”</span>
                            <CornerDownLeft className="h-3.5 w-3.5 text-fg-tertiary" strokeWidth={1.5} />
                          </Command.Item>
                        </Command.Group>
                      )}

                      {groups.map((group) => (
                        <Command.Group
                          key={group.label}
                          heading={group.label}
                          className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-label [&_[cmdk-group-heading]]:text-fg-tertiary"
                        >
                          {group.items.map((item) => {
                            const Icon = item.icon;
                            return (
                              <Command.Item key={item.href} value={item.name} onSelect={() => go(item.href)} className={itemClass}>
                                <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                                {item.name}
                              </Command.Item>
                            );
                          })}
                        </Command.Group>
                      ))}

                      <Command.Group
                        heading="Account"
                        className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-label [&_[cmdk-group-heading]]:text-fg-tertiary"
                      >
                        <Command.Item
                          value="Sign out"
                          onSelect={() => {
                            onOpenChange(false);
                            void logout();
                          }}
                          className={itemClass}
                        >
                          <LogOut className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                          Sign out
                        </Command.Item>
                      </Command.Group>
                    </Command.List>
                  </Command>
                </motion.div>
              </Dialog.Content>
            </div>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
};
