import { Check } from "lucide-react";
import { SECURITY_POINTS } from "./content";

export function SecuritySection() {
  return (
    <section className="landing-dark-glow-bg relative scroll-mt-24 overflow-hidden py-20 text-white lg:py-28" id="security">
      <div aria-hidden className="landing-grid-pattern pointer-events-none absolute inset-0 opacity-10" />
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12">
          <div className="space-y-6 lg:col-span-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-emerald-400">
              <span className="h-2 w-2 rounded-full bg-emerald-400 motion-safe:animate-pulse" />
              Zero auto-deductions
            </div>

            <h2 className="text-3xl font-bold leading-tight tracking-tight text-white sm:text-4xl">
              Spend credits only on audited, human-verified accounts.
            </h2>

            <p className="text-base leading-relaxed text-slate-300 sm:text-lg">
              Every contact reveal and HubSpot sync waits for a person to approve the lead first. Nothing is spent
              automatically, and nothing is sent to your CRM before an operator signs off.
            </p>

            <div className="space-y-4 pt-2">
              {SECURITY_POINTS.map((point) => (
                <div key={point.title} className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-emerald-500/20 text-emerald-400">
                    <Check className="h-4 w-4" />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-white">{point.title}</h4>
                    <p className="mt-0.5 text-xs text-slate-400">{point.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lg:col-span-6">
            <div className="rounded-2xl border border-slate-700/80 bg-slate-900/90 p-5 shadow-2xl ring-1 ring-white/10 backdrop-blur-xl sm:p-6">
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                  <span className="font-mono text-xs uppercase tracking-wider text-slate-400">Approval checkpoint</span>
                </div>
                <span className="rounded border border-slate-700 bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300">
                  Postgres RLS: verified
                </span>
              </div>

              <div className="mt-5 space-y-4">
                <div className="flex items-center justify-between rounded-lg border border-slate-700/60 bg-slate-800/60 p-4">
                  <div>
                    <div className="text-sm font-bold text-white">Apex Robotics, Inc.</div>
                    <div className="text-xs text-slate-400">apexrobotics.example • 185 employees • Boston, MA</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-sm font-bold text-emerald-400">96 / 100</div>
                    <div className="text-[10px] text-slate-400">Quality score</div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded border border-slate-800 bg-slate-800/40 p-2">
                    <span className="block text-[10px] text-slate-400">Speed signal</span>
                    <span className="font-bold text-emerald-400">Passed (0.8s)</span>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-800/40 p-2">
                    <span className="block text-[10px] text-slate-400">HubSpot status</span>
                    <span className="font-bold text-slate-300">Ready to sync</span>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-800/40 p-2">
                    <span className="block text-[10px] text-slate-400">Credit cost</span>
                    <span className="font-bold text-emerald-400">1 credit</span>
                  </div>
                </div>

                <div className="flex flex-col items-center gap-3 pt-2 sm:flex-row">
                  <button
                    type="button"
                    className="w-full flex-1 rounded-lg bg-emerald-700 px-4 py-2.5 text-center text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-800 sm:w-auto"
                  >
                    Approve &amp; deduct 1 credit
                  </button>
                  <button
                    type="button"
                    className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700 sm:w-auto"
                  >
                    Reject &amp; save credit
                  </button>
                </div>

                <div className="text-center">
                  <span className="font-mono text-[11px] text-slate-500">Demo preview — no credits are spent here</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
