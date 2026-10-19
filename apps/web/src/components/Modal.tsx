"use client";

import React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;
const EASE_IN = [0.4, 0, 1, 1] as const;

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

/** Centered dialog with focus trap, Escape to close and an animated backdrop. */
export const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, description, children, className }) => {
  const reduceMotion = useReducedMotion();
  const scaleFrom = reduceMotion ? 1 : 0.97;

  return (
    <Dialog.Root open={isOpen} onOpenChange={(next) => !next && onClose()}>
      <AnimatePresence>
        {isOpen && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-50"
                style={{ background: "var(--backdrop)" }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1, transition: { duration: 0.25, ease: EASE_OUT } }}
                exit={{ opacity: 0, transition: { duration: 0.18, ease: EASE_IN } }}
              />
            </Dialog.Overlay>
            <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4">
              <Dialog.Content asChild forceMount aria-describedby={description ? undefined : undefined}>
                <motion.div
                  className={cn(
                    "pointer-events-auto max-h-[calc(100vh-2rem)] w-full max-w-lg overflow-y-auto rounded-sheet border border-border bg-surface p-6 shadow-modal",
                    className
                  )}
                  initial={{ opacity: 0, scale: scaleFrom }}
                  animate={{ opacity: 1, scale: 1, transition: { duration: 0.25, ease: EASE_OUT } }}
                  exit={{ opacity: 0, scale: scaleFrom, transition: { duration: 0.18, ease: EASE_IN } }}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <Dialog.Title className="text-xl font-semibold text-fg">{title}</Dialog.Title>
                      {description ? (
                        <Dialog.Description className="mt-1 text-sm text-fg-secondary">{description}</Dialog.Description>
                      ) : null}
                    </div>
                    <Dialog.Close
                      aria-label="Close"
                      className="focus-ring -mr-2 -mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg"
                    >
                      <X className="h-4 w-4" strokeWidth={1.5} />
                    </Dialog.Close>
                  </div>
                  <div className="mt-5">{children}</div>
                </motion.div>
              </Dialog.Content>
            </div>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
};
