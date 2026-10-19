import { STATS } from "./content";

export function StatsRow() {
  return (
    <section className="border-b border-slate-200 bg-white">
      <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
        <div className="grid grid-cols-1 divide-y divide-slate-200/90 md:grid-cols-3 md:divide-x md:divide-y-0">
          {STATS.map((stat) => (
            <div key={stat.label} className="flex flex-col justify-center py-4 first:pl-0 md:px-8 md:py-0">
              <div className="flex items-baseline gap-2">
                <span className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">{stat.value}</span>
                {stat.badge && (
                  <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
                    {stat.badge}
                  </span>
                )}
              </div>
              <p className="mt-2 text-sm font-medium text-slate-600 sm:text-base">{stat.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
