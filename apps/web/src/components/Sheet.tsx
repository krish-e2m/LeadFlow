"use client";

import React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;
const EASE_IN = [0.4, 0, 1, 1] as const;

interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  /** Sticky footer, e.g. the primary actions. */
  footer?: React.ReactNode;
  /** Icon buttons shown next to the close button. */
  headerActions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

/** Right-hand side sheet (520px; full screen on mobile). The page behind stays visible. */
export const Sheet: React.FC<SheetProps> = ({ open, onOpenChange, title, description, footer, headerActions, children, className }) => {
  const reduceMotion = useReducedMotion();
  const offset = reduceMotion ? 0 : 24;

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
                animate={{ opacity: 1, transition: { duration: 0.28, ease: EASE_OUT } }}
                exit={{ opacity: 0, transition: { duration: 0.2, ease: EASE_IN } }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount aria-describedby={description ? undefined : undefined}>
              <motion.div
                className={cn(
                  "fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-border bg-surface shadow-modal sm:w-sheet sm:rounded-l-sheet",
                  className
                )}
                initial={{ x: offset, opacity: 0 }}
                animate={{ x: 0, opacity: 1, transition: { duration: 0.28, ease: EASE_OUT } }}
                exit={{ x: offset, opacity: 0, transition: { duration: 0.2, ease: EASE_IN } }}
              >
                <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
                  <div className="min-w-0">
                    <Dialog.Title className="truncate text-xl font-semibold text-fg">{title}</Dialog.Title>
                    {description ? (
                      <Dialog.Description className="mt-0.5 truncate text-sm text-fg-secondary">
                        {description}
                      </Dialog.Description>
                    ) : null}
                  </div>
                  <div className="-mr-2 -mt-1 flex shrink-0 items-center gap-1">
                    {headerActions}
                    <Dialog.Close
                      aria-label="Close"
                      className="focus-ring inline-flex h-8 w-8 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg"
                    >
                      <X className="h-4 w-4" strokeWidth={1.5} />
                    </Dialog.Close>
                  </div>
                </header>
                <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
                {footer ? <footer className="border-t border-border bg-surface px-6 py-3">{footer}</footer> : null}
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
};
