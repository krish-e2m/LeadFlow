import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { HeroProductMockup } from "./HeroProductMockup";

export function Hero() {
  return (
    <section className="landing-mesh-bg relative overflow-hidden border-b border-slate-200/60 pb-20 pt-16 lg:pb-32 lg:pt-24">
      <div aria-hidden className="landing-grid-pattern pointer-events-none absolute inset-0 opacity-40" />
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12 lg:gap-8">
          <div className="flex flex-col items-start space-y-6 lg:col-span-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200/80 bg-emerald-50/80 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-emerald-800 shadow-sm backdrop-blur-sm">
              <span className="flex h-2 w-2 rounded-full bg-emerald-500 motion-safe:animate-pulse" />
              Engineered B2B lead scoring • 22 signals
            </div>

            <h1 className="max-w-xl text-4xl font-semibold leading-[1.08] tracking-tight text-slate-900 sm:text-5xl lg:text-6xl">
              Know which companies are worth contacting before you spend a credit.
            </h1>

            <p className="max-w-xl text-base leading-relaxed text-slate-600 sm:text-lg">
              LeadFlow scores companies on 22 website and marketing signals, shows the evidence behind every score,
              and keeps a person in control of each step from sourcing to HubSpot.
            </p>

            <div className="flex flex-wrap items-center gap-4 pt-2">
              <Link
                href="/signup"
                className="group inline-flex items-center gap-2.5 rounded-full bg-brand-700 px-6 py-3.5 text-sm font-semibold text-white shadow-md transition-all duration-200 hover:bg-brand-800 focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2"
              >
                Create workspace
                <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" />
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white/80 px-5 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900"
              >
                Sign in
              </Link>
            </div>
          </div>

          <div className="relative lg:col-span-6">
            <HeroProductMockup />
          </div>
        </div>
      </div>
    </section>
  );
}
