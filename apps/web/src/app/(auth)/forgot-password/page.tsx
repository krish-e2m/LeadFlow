"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { AuthShell, FormError, textLinkClass } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Input } from "@/components/Input";
import { apiClient } from "@/lib/api-client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      await apiClient.post("/auth/forgot-password", { email });
      setIsSubmitted(true);
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : "The reset email couldn't be sent. Try again in a moment.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthShell
      title="Reset your password"
      description="Enter your email and we'll send you a reset link."
      footer={
        <Link href="/login" className={textLinkClass}>
          Back to sign in
        </Link>
      }
    >
      {isSubmitted ? (
        <p className="flex items-start gap-3 text-sm text-fg-secondary" role="status">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" strokeWidth={2} aria-hidden="true" />
          <span>
            If an account exists for <span className="font-medium text-fg">{email}</span>, a reset link is on its way. It can take a few minutes to arrive.
          </span>
        </p>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <FormError>{error}</FormError>}
          <Input label="Email" type="email" autoComplete="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <Button type="submit" size="lg" className="w-full" isLoading={isLoading}>
            Send reset link
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
