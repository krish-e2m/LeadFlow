"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { apiClient, setCsrfToken } from "@/lib/api-client";

export interface AuthUser {
  id: string;
  email: string;
  full_name?: string | null;
  role: "super_admin" | "org_admin" | "client_viewer";
  org_id?: string | null;
  org_name?: string | null;
  must_reset_password: boolean;
  avatar_url?: string | null;
  // Not rendered anywhere; apiClient reads this once via setCsrfToken below. See api-client.ts for why.
  csrf_token?: string | null;
}

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<AuthUser | null>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  logout: async () => {},
  refreshUser: async () => null,
});

const PUBLIC_ROUTES = ["/", "/login", "/signup", "/forgot-password", "/reset-password"];

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refreshUser = useCallback(async () => {
    try {
      const profile = await apiClient.get<AuthUser>("/auth/me");
      setCsrfToken(profile.csrf_token ?? null);
      setUser(profile);
      return profile;
    } catch {
      setUser(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Route protection lives here, not in middleware: the session lives in a cookie on the API's own
  // domain (a different origin from this app), so only a real client-side call to /auth/me can ever
  // know whether someone is actually signed in.
  useEffect(() => {
    const isPublic = PUBLIC_ROUTES.includes(pathname);
    if (isPublic) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    refreshUser().then((profile) => {
      if (cancelled) return;
      if (!profile) router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
    });
    return () => {
      cancelled = true;
    };
  }, [pathname, refreshUser, router]);

  // Already signed in and sitting on /login or /signup: go straight to the dashboard.
  useEffect(() => {
    if (!isLoading && user && (pathname === "/login" || pathname === "/signup")) {
      router.replace("/dashboard");
    }
  }, [isLoading, user, pathname, router]);

  const logout = async () => {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      setCsrfToken(null);
      setUser(null);
      router.push("/login");
    }
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
