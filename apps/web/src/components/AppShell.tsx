"use client";

import React, { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { CommandPalette } from "@/components/CommandPalette";

const COLLAPSE_KEY = "leadflow:sidebar-collapsed";
const EASE_OUT = [0.16, 1, 0.3, 1] as const;
const EASE_IN = [0.4, 0, 1, 1] as const;

/** Sidebar + top bar shared by the admin and client views; only the navigation items differ by role. */
export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const pathname = usePathname();
  const reduceMotion = useReducedMotion();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutLabel, setShortcutLabel] = useState("Ctrl K");

  // Restore the collapsed preference. Browser storage can be unavailable, so it stays optional.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable: keep default */
    }
    setShortcutLabel(/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl K");
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* storage unavailable: preference lasts for this session only */
      }
      return next;
    });
  }, []);

  // Close the drawer whenever the route changes.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // ⌘K / Ctrl+K opens the palette from anywhere.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    // Same gradient canvas as the marketing site and the auth pages: the sidebar/header stay solid
    // white on top of it, and every data table/card sits in its own opaque surface, so the dense
    // screens stay fully readable — only the page background carries the homepage's look.
    <div className="landing-mesh-bg relative min-h-screen bg-background">
      <div aria-hidden className="landing-grid-pattern pointer-events-none fixed inset-0 z-0 opacity-40" />
      <a
        href="#main"
        className="focus-ring sr-only z-[80] rounded-control bg-surface px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside
        className="fixed inset-y-0 left-0 z-40 hidden border-r border-border lg:block"
        style={{ width: collapsed ? "var(--sidebar-rail-width)" : "var(--sidebar-width)" }}
      >
        <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} indicatorId="desktop" />
      </aside>

      {/* Mobile drawer */}
      <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
        <AnimatePresence>
          {drawerOpen && (
            <Dialog.Portal forceMount>
              <Dialog.Overlay asChild forceMount>
                <motion.div
                  className="fixed inset-0 z-50 lg:hidden"
                  style={{ background: "var(--backdrop)" }}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, transition: { duration: 0.25, ease: EASE_OUT } }}
                  exit={{ opacity: 0, transition: { duration: 0.18, ease: EASE_IN } }}
                />
              </Dialog.Overlay>
              <Dialog.Content asChild forceMount aria-describedby={undefined}>
                <motion.div
                  className="fixed inset-y-0 left-0 z-50 w-sidebar max-w-[85vw] border-r border-border shadow-modal lg:hidden"
                  initial={{ x: reduceMotion ? 0 : -24, opacity: 0 }}
                  animate={{ x: 0, opacity: 1, transition: { duration: 0.28, ease: EASE_OUT } }}
                  exit={{ x: reduceMotion ? 0 : -24, opacity: 0, transition: { duration: 0.2, ease: EASE_IN } }}
                >
                  <Dialog.Title className="sr-only">Navigation</Dialog.Title>
                  <Sidebar indicatorId="drawer" onNavigate={() => setDrawerOpen(false)} />
                </motion.div>
              </Dialog.Content>
            </Dialog.Portal>
          )}
        </AnimatePresence>
      </Dialog.Root>

      <div
        className={cn("flex min-h-screen flex-col", collapsed ? "lg:pl-[var(--sidebar-rail-width)]" : "lg:pl-[var(--sidebar-width)]")}
      >
        <Header
          onOpenMenu={() => setDrawerOpen(true)}
          onOpenSearch={() => setPaletteOpen(true)}
          shortcutLabel={shortcutLabel}
        />
        <main id="main" className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {/* Every route swap gets the same quiet fade/rise, keyed on the path so it never
           * animates across content that merely re-rendered (e.g. data refetching in place). */}
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.div
              key={pathname}
              className="mx-auto w-full max-w-screen-2xl space-y-6"
              initial={reduceMotion ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0, transition: { duration: 0.22, ease: EASE_OUT } }}
              exit={reduceMotion ? undefined : { opacity: 0, transition: { duration: 0.12, ease: EASE_IN } }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
};
