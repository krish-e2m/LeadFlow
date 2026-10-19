import { SiteHeader } from "@/components/landing/SiteHeader";
import { Hero } from "@/components/landing/Hero";
import { StatsRow } from "@/components/landing/StatsRow";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { SecuritySection } from "@/components/landing/SecuritySection";
import { FinalCta } from "@/components/landing/FinalCta";
import { SiteFooter } from "@/components/landing/SiteFooter";

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-50/60 text-slate-800 antialiased selection:bg-brand-500 selection:text-white">
      <SiteHeader />
      <main>
        <Hero />
        <StatsRow />
        <HowItWorks />
        <SecuritySection />
        <FinalCta />
      </main>
      <SiteFooter />
    </div>
  );
}
