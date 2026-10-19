"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Check } from "lucide-react";
import { AuthShell, FormError, textLinkClass } from "@/components/AuthShell";
import { Button } from "@/components/Button";
import { Input } from "@/components/Input";
import { Select } from "@/components/Select";
import { StatusBadge } from "@/components/Badge";
import { apiClient } from "@/lib/api-client";
import { AuthUser, useAuth } from "@/lib/auth-context";
import { AccessRequest, PublicOrganizationItem, UserRole } from "@/types";
import { cn } from "@/lib/utils";
import { GoogleSignInButton, AuthDivider } from "@/components/GoogleSignInButton";

interface LoginApiResponse {
  user: AuthUser;
  message: string;
}

type AccessFlowMode = "login" | "request_access";
type RequestOption = "org_admin" | "member";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** Bordered radio option used for the access request choices. */
const RadioCard: React.FC<{
  name: string;
  checked: boolean;
  onChange: () => void;
  title: string;
  description: string;
}> = ({ name, checked, onChange, title, description }) => (
  <label
    className={cn(
      "focus-ring-within block cursor-pointer rounded-card border p-3.5 transition-colors duration-fast",
      checked ? "border-accent bg-accent-subtle" : "border-border bg-surface hover:border-border-strong"
    )}
  >
    <input type="radio" name={name} checked={checked} onChange={onChange} className="sr-only" />
    <span className="block text-sm font-medium text-fg">{title}</span>
    <span className="mt-0.5 block text-caption text-fg-secondary">{description}</span>
  </label>
);

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refreshUser } = useAuth();

  const [mode, setMode] = useState<AccessFlowMode>("login");

  // Sign in
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check URL query parameters for OAuth errors
  useEffect(() => {
    const queryError = searchParams.get("error");
    if (queryError) {
      setError(queryError);
    }
  }, [searchParams]);

  // Request access
  const [selectedOption, setSelectedOption] = useState<RequestOption>("org_admin");
  const [organizations, setOrganizations] = useState<PublicOrganizationItem[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [orgSearch, setOrgSearch] = useState("");
  const [reqFullName, setReqFullName] = useState("");
  const [reqEmail, setReqEmail] = useState("");
  const [reqPassword, setReqPassword] = useState("");
  const [reqRole, setReqRole] = useState<"client_viewer" | "org_admin">("client_viewer");
  const [isSubmittingReq, setIsSubmittingReq] = useState(false);
  const [submittedRequest, setSubmittedRequest] = useState<AccessRequest | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);

  const handleEmailChange = (newEmail: string) => {
    setReqEmail(newEmail);
    if (newEmail.includes("@") && organizations.length > 0) {
      const domain = newEmail.split("@")[1]?.split(".")[0]?.toLowerCase();
      if (domain && domain.length >= 2) {
        const matchingOrg = organizations.find((o) => o.slug.toLowerCase().includes(domain) || o.name.toLowerCase().includes(domain));
        if (matchingOrg) setSelectedOrgId(matchingOrg.id);
      }
    }
  };

  // Fetch active organizations once, for the access request form
  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<PublicOrganizationItem[]>("/auth/organizations")
      .then((orgs) => {
        if (cancelled) return;
        setOrganizations(orgs);
        setSelectedOrgId((current) => current || (orgs.length > 0 ? orgs[0].id : ""));
      })
      .catch(() => {
        /* The form still works for sign in; the organization list stays empty. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      const res = await apiClient.post<LoginApiResponse>("/auth/login", { email, password });
      await refreshUser();

      // The route guard sends people here with ?redirect=; ?returnUrl= is the older name.
      const returnUrl = searchParams.get("redirect") ?? searchParams.get("returnUrl");
      if (returnUrl && returnUrl.startsWith("/") && !returnUrl.startsWith("//")) {
        router.push(returnUrl);
      } else if (res.user.role === "client_viewer") {
        router.push("/portal");
      } else {
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "That email and password don't match. Check them and try again."));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRequestAccessSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmittingReq(true);
    setReqError(null);

    if (!selectedOrgId) {
      setReqError("Choose the organization you want to join.");
      setIsSubmittingReq(false);
      return;
    }

    const effectiveRole: UserRole = selectedOption === "org_admin" ? "org_admin" : reqRole;

    try {
      const res = await apiClient.post<AccessRequest>("/auth/access-requests", {
        email: reqEmail.trim(),
        password: reqPassword,
        full_name: reqFullName.trim() || undefined,
        org_id: selectedOrgId,
        requested_role: effectiveRole,
      });
      setSubmittedRequest(res);
    } catch (err: unknown) {
      setReqError(errorMessage(err, "The request couldn't be submitted. Try again in a moment."));
    } finally {
      setIsSubmittingReq(false);
    }
  };

  const selectedOrgName = organizations.find((o) => o.id === selectedOrgId)?.name || "the selected organization";
  const filteredOrgs = organizations.filter(
    (org) => org.name.toLowerCase().includes(orgSearch.toLowerCase()) || org.slug.toLowerCase().includes(orgSearch.toLowerCase())
  );
  const wantsAdmin = selectedOption === "org_admin" || reqRole === "org_admin";

  if (mode === "login") {
    return (
      <AuthShell
        title="Sign in"
        description="Use your work email to open your LeadFlow workspace."
        footer={
          <>
            Need access?{" "}
            <button type="button" onClick={() => setMode("request_access")} className={textLinkClass}>
              Request access
            </button>
          </>
        }
      >
        {error && <FormError>{error}</FormError>}
        <GoogleSignInButton
          returnUrl={searchParams.get("redirect") ?? searchParams.get("returnUrl") ?? "/dashboard"}
          onError={(msg) => setError(msg)}
        />
        <AuthDivider />
        <form onSubmit={handleLoginSubmit} className="space-y-4">
          <Input
            label="Email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <div className="space-y-1.5">
            <Input
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <div className="text-right">
              <Link href="/forgot-password" className={cn(textLinkClass, "text-caption")}>
                Forgot password?
              </Link>
            </div>
          </div>
          <Button type="submit" size="lg" className="w-full" isLoading={isLoading}>
            Sign in
          </Button>
        </form>
      </AuthShell>
    );
  }

  if (submittedRequest) {
    return (
      <AuthShell title="Request submitted" width="wide">
        <div className="space-y-5">
          <p className="flex items-start gap-3 text-sm text-fg-secondary">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" strokeWidth={2} aria-hidden="true" />
            {submittedRequest.requested_role === "org_admin" ? (
              <span>
                Your request for admin access to <span className="font-medium text-fg">{submittedRequest.org_name || selectedOrgName}</span> is waiting
                for a LeadFlow super admin to review it.
              </span>
            ) : (
              <span>
                Your request to join <span className="font-medium text-fg">{submittedRequest.org_name || selectedOrgName}</span> as a client viewer is
                waiting for that organization's admins to review it.
              </span>
            )}
          </p>

          <dl className="divide-y divide-border rounded-card border border-border text-sm">
            <div className="flex items-center justify-between px-3 py-2.5">
              <dt className="text-fg-secondary">Email</dt>
              <dd className="font-medium text-fg">{submittedRequest.email}</dd>
            </div>
            <div className="flex items-center justify-between px-3 py-2.5">
              <dt className="text-fg-secondary">Requested role</dt>
              <dd className="font-medium text-fg">{submittedRequest.requested_role === "org_admin" ? "Org admin" : "Client viewer"}</dd>
            </div>
            <div className="flex items-center justify-between px-3 py-2.5">
              <dt className="text-fg-secondary">Status</dt>
              <dd>
                <StatusBadge tone="warning">{submittedRequest.status}</StatusBadge>
              </dd>
            </div>
          </dl>

          <Button
            type="button"
            variant="secondary"
            size="lg"
            className="w-full"
            onClick={() => {
              setEmail(submittedRequest.email);
              setSubmittedRequest(null);
              setMode("login");
            }}
          >
            Back to sign in
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Request access"
      description="Every request is reviewed before an account is activated."
      width="wide"
      footer={
        <>
          Already have an account?{" "}
          <button type="button" onClick={() => setMode("login")} className={textLinkClass}>
            Sign in
          </button>
        </>
      }
    >
      {reqError && <FormError>{reqError}</FormError>}

      <form onSubmit={handleRequestAccessSubmit} className="space-y-5">
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="sr-only">Type of access</legend>
          <RadioCard
            name="access_option"
            checked={selectedOption === "org_admin"}
            onChange={() => setSelectedOption("org_admin")}
            title="Organization admin"
            description="Manage searches, engines and team members. Approved by a super admin."
          />
          <RadioCard
            name="access_option"
            checked={selectedOption === "member"}
            onChange={() => setSelectedOption("member")}
            title="Member"
            description="Join an organization that already uses LeadFlow. Approved by its admins."
          />
        </fieldset>

        <div className="space-y-2">
          <Input
            label="Organization"
            placeholder="Filter by name"
            value={orgSearch}
            onChange={(e) => setOrgSearch(e.target.value)}
            helper={organizations.length === 0 ? "Loading organizations…" : `${filteredOrgs.length} of ${organizations.length} shown`}
          />
          <Select
            value={selectedOrgId}
            onValueChange={setSelectedOrgId}
            options={filteredOrgs.map((org) => ({ value: org.id, label: `${org.name} (${org.slug})` }))}
            placeholder="Choose an organization"
            aria-label="Organization"
          />
        </div>

        {selectedOption === "member" && (
          <fieldset className="grid gap-3 sm:grid-cols-2">
            <legend className="mb-1.5 text-caption font-medium text-fg">Access level</legend>
            <RadioCard
              name="requested_level"
              checked={reqRole === "client_viewer"}
              onChange={() => setReqRole("client_viewer")}
              title="Client portal"
              description="Read-only view of approved leads."
            />
            <RadioCard
              name="requested_level"
              checked={reqRole === "org_admin"}
              onChange={() => setReqRole("org_admin")}
              title="Organization admin"
              description="Full workflow access."
            />
          </fieldset>
        )}

        <Input label="Full name" autoComplete="name" value={reqFullName} onChange={(e) => setReqFullName(e.target.value)} required />
        <Input
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={reqEmail}
          onChange={(e) => handleEmailChange(e.target.value)}
          required
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          helper="At least 8 characters. It becomes your password once the request is approved."
          value={reqPassword}
          onChange={(e) => setReqPassword(e.target.value)}
          required
          minLength={8}
        />

        <p className="text-caption text-fg-secondary">
          {wantsAdmin
            ? `Admin requests for ${selectedOrgName} are reviewed by a LeadFlow super admin.`
            : `Requests to join ${selectedOrgName} go to that organization's admins.`}
        </p>

        <Button type="submit" size="lg" className="w-full" isLoading={isSubmittingReq}>
          Submit request
        </Button>
      </form>
    </AuthShell>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-background" aria-busy="true" />}>
      <LoginForm />
    </Suspense>
  );
}
