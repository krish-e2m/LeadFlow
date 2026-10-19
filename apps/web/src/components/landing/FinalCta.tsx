import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function FinalCta() {
  return (
    <section className="scroll-mt-24 border-b border-slate-200 bg-white py-20" id="create-workspace">
      <div className="mx-auto max-w-5xl px-4 text-center sm:px-6 lg:px-8">
        <div className="landing-mesh-bg relative overflow-hidden rounded-3xl border border-slate-200/90 bg-slate-50/70 p-8 shadow-landing-card sm:p-14">
          <h2 className="relative mx-auto max-w-3xl text-3xl font-bold leading-tight tracking-tight text-slate-900 sm:text-4xl lg:text-5xl">
            Know which companies are worth contacting before you spend a credit.
          </h2>
          <p className="relative mx-auto mt-4 max-w-2xl text-base text-slate-600 sm:text-lg">
            LeadFlow scores companies on 22 website and marketing signals, shows the evidence behind every score, and
            keeps a person in control of each step from sourcing to HubSpot.
          </p>
          <div className="relative mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link
              href="/signup"
              className="group inline-flex items-center gap-2 rounded-full bg-slate-900 px-7 py-3.5 text-sm font-semibold text-white shadow-md transition-all duration-200 hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2"
            >
              Create workspace
              <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white px-6 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900"
            >
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
