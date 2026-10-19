"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  description?: string;
}

interface ToastApi {
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DISMISS_AFTER_MS = 4000;

const icons = { success: CheckCircle2, error: AlertCircle, info: Info } as const;
const iconColor = { success: "text-success", error: "text-danger", info: "text-accent" } as const;

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const reduceMotion = useReducedMotion();

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, title: string, description?: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-3), { id, kind, title, description }]);
      window.setTimeout(() => dismiss(id), DISMISS_AFTER_MS);
    },
    [dismiss]
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (title, description) => push("success", title, description),
      error: (title, description) => push("error", title, description),
      info: (title, description) => push("info", title, description),
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ol
        aria-live="polite"
        aria-label="Notifications"
        className="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-[calc(100vw-2rem)] max-w-[380px] flex-col gap-2"
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => {
            const Icon = icons[toast.kind];
            return (
              <motion.li
                key={toast.id}
                layout={!reduceMotion}
                initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, ease: [0.16, 1, 0.3, 1] } }}
                exit={{ opacity: 0, transition: { duration: 0.15, ease: [0.4, 0, 1, 1] } }}
                role={toast.kind === "error" ? "alert" : "status"}
                className="pointer-events-auto flex items-start gap-3 rounded-card border border-border bg-surface p-3 shadow-pop"
              >
                <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconColor[toast.kind])} strokeWidth={1.5} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-fg">{toast.title}</p>
                  {toast.description ? <p className="mt-0.5 text-caption text-fg-secondary">{toast.description}</p> : null}
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(toast.id)}
                  aria-label="Dismiss notification"
                  className="focus-ring -mr-1 -mt-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg"
                >
                  <X className="h-3.5 w-3.5" strokeWidth={1.5} />
                </button>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>
    </ToastContext.Provider>
  );
};

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
