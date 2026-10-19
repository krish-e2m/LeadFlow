import { Code2, Gauge, Search, ShieldCheck } from "lucide-react";
import { STEPS } from "./content";

const STEP_ICONS = [Search, Code2, Gauge, ShieldCheck];

export function HowItWorks() {
  return (
    <section className="scroll-mt-24 border-b border-slate-200/80 bg-slate-50/70 py-20 lg:py-28" id="how-it-works">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="max-w-2xl">
          <span className="text-xs font-bold uppercase tracking-widest text-brand-700">Methodology</span>
          <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">How it works</h2>
          <p className="mt-3 text-base text-slate-600">
            A systematic four-phase pipeline designed to eliminate wasted outreach and protect sales rep velocity.
          </p>
        </div>

        <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, index) => {
            const Icon = STEP_ICONS[index];
            return (
              <div
                key={step.title}
                className="landing-hover-lift flex flex-col justify-between rounded-xl border border-slate-200/80 bg-white p-6 shadow-sm"
              >
                <div>
                  <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                    <span className="inline-flex items-center rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                      Step {index + 1}
                    </span>
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
                      <Icon className="h-4 w-4" aria-hidden />
                    </div>
                  </div>
                  <h3 className="mt-5 text-lg font-bold text-slate-900">{step.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">{step.body}</p>
                </div>
                <div
                  className={
                    "mt-6 border-t border-slate-100 pt-4 font-mono text-[11px] " +
                    (index === 0 ? "text-slate-400" : index === 2 ? "text-slate-500" : "font-medium text-emerald-700")
                  }
                >
                  {step.meta}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
