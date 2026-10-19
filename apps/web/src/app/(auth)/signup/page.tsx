"use client";

import React, { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthShell, FormError, textLinkClass } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Input } from "@/components/Input";
import { apiClient } from "@/lib/api-client";
import { AuthUser, useAuth } from "@/lib/auth-context";
import { GoogleSignInButton, AuthDivider } from "@/components/GoogleSignInButton";

interface SignupApiResponse {
  user: AuthUser;
  message: string;
}

function SignupForm() {
  const router = useRouter();
  const { refreshUser } = useAuth();

  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    if (password.length < 8) {
      setError("Use a password with at least 8 characters.");
      setIsLoading(false);
      return;
    }

    if (!orgName.trim()) {
      setError("Enter your organization's name.");
      setIsLoading(false);
      return;
    }

    try {
      await apiClient.post<SignupApiResponse>("/auth/signup", {
        email: email.trim(),
        password,
        organization_name: orgName.trim(),
        full_name: fullName.trim() || undefined,
      });

      await refreshUser();
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : "The account couldn't be created. Check your details and try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthShell
      title="Create your workspace"
      description="Set up an organization and start sourcing leads."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className={textLinkClass}>
            Sign in
          </Link>
        </>
      }
    >
      {error && <FormError>{error}</FormError>}
      <GoogleSignInButton
        text="Sign up with Google"
        returnUrl="/dashboard"
        onError={(msg) => setError(msg)}
      />
      <AuthDivider label="or register with email" />
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input label="Organization name" autoComplete="organization" placeholder="Acme Growth" value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
        <Input label="Your name" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
        <Input label="Work email" type="email" autoComplete="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          helper="At least 8 characters."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={8}
          required
        />
        <Button type="submit" size="lg" className="w-full" isLoading={isLoading}>
          Create workspace
        </Button>
      </form>
    </AuthShell>
  );
}

export default function SignupPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-background" aria-busy="true" />}>
      <SignupForm />
    </Suspense>
  );
}
