import Link from "next/link";
import { FOOTER_LEGAL_ITEMS, FOOTER_PRODUCT_LINKS, FOOTER_SECURITY_LINKS } from "./content";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="bg-white py-14 text-sm text-slate-600">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 gap-8 border-b border-slate-200 pb-12 md:grid-cols-5">
          <div className="col-span-2">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-xs font-bold text-white shadow-sm">
                LF
              </span>
              <span className="text-lg font-bold tracking-tight text-slate-900">LeadFlow</span>
            </div>
            <p className="mt-4 max-w-sm text-xs leading-relaxed text-slate-500">
              Engineered B2B lead scoring and verification. Audit 22 signals, keep full human control, and sync to
              HubSpot only after a person approves.
            </p>
            <div className="mt-4 font-mono text-xs text-slate-400">Postgres row-level security enforced</div>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">Product</h4>
            <ul className="mt-3 space-y-2 text-xs">
              {FOOTER_PRODUCT_LINKS.map((link) => (
                <li key={link.label}>
                  <a className="transition hover:text-slate-900" href={link.href}>
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">Security</h4>
            <ul className="mt-3 space-y-2 text-xs">
              {FOOTER_SECURITY_LINKS.map((link) => (
                <li key={link.label}>
                  <a className="transition hover:text-slate-900" href={link.href}>
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">Legal</h4>
            {/* No legal pages exist yet, so these are plain text rather than dead links. */}
            <ul className="mt-3 space-y-2 text-xs text-slate-400">
              {FOOTER_LEGAL_ITEMS.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-8 flex flex-col items-center justify-between text-xs text-slate-500 sm:flex-row">
          <p>© {year} LeadFlow. All rights reserved.</p>
          <Link href="/login" className="mt-4 text-slate-500 transition hover:text-slate-900 sm:mt-0">
            Sign in
          </Link>
        </div>
      </div>
    </footer>
  );
}
