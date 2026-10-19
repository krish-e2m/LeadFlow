"use client";

import Link from "next/link";
import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { NAV_LINKS, PRODUCT_DROPDOWN_ITEMS } from "./content";

/** Sticky marketing header: scroll shadow, a keyboard/touch-accessible Product disclosure, and a
 * mobile nav panel. Scoped to the landing page — it never touches the dashboard chrome. */
export function SiteHeader() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Smooth in-page scrolling for the anchor links below, scoped to while this page is mounted
  // (the dashboard never gets this behavior).
  useEffect(() => {
    document.documentElement.classList.add("scroll-smooth");
    return () => document.documentElement.classList.remove("scroll-smooth");
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [mobileOpen]);

  return (
    <header
      className={cn(
        "sticky top-0 z-50 w-full border-b bg-white/85 backdrop-blur-md transition-all duration-300",
        scrolled ? "border-slate-200 shadow-[0_1px_0_0_rgba(15,23,42,0.06),0_8px_24px_-16px_rgba(15,23,42,0.25)]" : "border-slate-200/80 shadow-none"
      )}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-8">
          <Link aria-label="LeadFlow home" className="group flex items-center gap-2.5" href="/">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-xs font-bold tracking-wider text-white shadow-sm ring-1 ring-slate-800/80 transition-transform group-hover:scale-105">
              LF
            </span>
            <span className="text-lg font-bold tracking-tight text-slate-900">LeadFlow</span>
          </Link>

          <nav aria-label="Main" className="hidden md:flex items-center gap-1">
            <ProductDropdown />
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100/60 hover:text-slate-900"
              >
                {link.label}
              </a>
            ))}
          </nav>
        </div>

        <div className="hidden md:flex items-center gap-2 text-sm text-slate-500">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
          22 signals, human-reviewed
        </div>

        <button
          type="button"
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
          aria-controls="landing-mobile-nav"
          onClick={() => setMobileOpen((o) => !o)}
          className="flex h-9 w-9 items-center justify-center rounded-md text-slate-700 hover:bg-slate-100 md:hidden"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {mobileOpen && (
        <div id="landing-mobile-nav" className="border-t border-slate-200 bg-white md:hidden">
          <nav aria-label="Mobile" className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-3 sm:px-6">
            {PRODUCT_DROPDOWN_ITEMS.map((item) => (
              <a
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className="rounded-md px-3 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                {item.label}
              </a>
            ))}
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className="rounded-md px-3 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                {link.label}
              </a>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-slate-100 pt-3">
              <Link
                href="/login"
                onClick={() => setMobileOpen(false)}
                className="rounded-md border border-slate-300 px-3 py-2.5 text-center text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                Sign in
              </Link>
              <Link
                href="/signup"
                onClick={() => setMobileOpen(false)}
                className="rounded-md bg-slate-900 px-3 py-2.5 text-center text-sm font-semibold text-white hover:bg-brand-700"
              >
                Create workspace
              </Link>
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}

function ProductDropdown() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    // Click-only toggle (no hover-open): combining hover with a click toggle means a mouse user's
    // hover sets it open, then their click immediately toggles it back shut. Click + Escape +
    // outside-click is the accessible pattern this needs for keyboard and touch anyway.
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100/60 hover:text-slate-900"
      >
        Product
        <ChevronDown className={cn("h-4 w-4 text-slate-400 transition-transform duration-200", open && "rotate-180")} />
      </button>

      <div
        role="group"
        aria-label="Product"
        className={cn(
          "absolute left-0 top-full w-72 pt-2 transition-all duration-150",
          open ? "visible translate-y-0 opacity-100" : "invisible -translate-y-1 opacity-0"
        )}
      >
        <div className="rounded-xl border border-slate-200 bg-white p-2 shadow-xl ring-1 ring-black/5">
          {PRODUCT_DROPDOWN_ITEMS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className="flex flex-col gap-0.5 rounded-lg p-2.5 transition-colors hover:bg-slate-50"
            >
              <span className="flex items-center gap-2 text-xs font-medium text-slate-900">
                <span className={cn("h-2 w-2 rounded-full", item.dotClassName)} />
                {item.label}
              </span>
              <span className="pl-4 text-xs text-slate-500">{item.description}</span>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
