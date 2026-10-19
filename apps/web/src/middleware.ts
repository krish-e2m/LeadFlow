import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/leads",
  "/searches",
  "/audiences",
  "/engines",
  "/drafts",
  "/portal",
  "/admin",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const hasAccessToken = request.cookies.has("leadflow_access_token");
  const hasRefreshToken = request.cookies.has("leadflow_refresh_token");
  const isAuthenticated = hasAccessToken || hasRefreshToken;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );

  // If user is unauthenticated and tries to visit a protected route, redirect to login
  if (isProtected && !isAuthenticated) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // If user is already authenticated and visits /login or /signup, redirect to dashboard
  if ((pathname === "/login" || pathname === "/signup") && isAuthenticated) {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = "/dashboard";
    return NextResponse.redirect(dashboardUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/leads/:path*",
    "/searches/:path*",
    "/audiences/:path*",
    "/engines/:path*",
    "/drafts/:path*",
    "/portal/:path*",
    "/admin/:path*",
    "/login",
    "/signup",
  ],
};
