import {
  Building2,
  FileCheck2,
  LayoutDashboard,
  MailCheck,
  type LucideIcon,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Users2,
} from "lucide-react";

export type AppRole = "super_admin" | "org_admin" | "client_viewer";

export interface NavItem {
  name: string;
  href: string;
  icon: LucideIcon;
  allowedRoles: AppRole[];
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

const ALL: AppRole[] = ["super_admin", "org_admin", "client_viewer"];
const ADMIN: AppRole[] = ["super_admin", "org_admin"];

export const navGroups: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard, allowedRoles: ALL },
      { name: "Leads", href: "/leads", icon: Users2, allowedRoles: ALL },
      { name: "Client portal", href: "/portal", icon: FileCheck2, allowedRoles: ALL },
    ],
  },
  {
    label: "Prospecting",
    items: [
      { name: "New search", href: "/searches/new", icon: Search, allowedRoles: ADMIN },
      { name: "Audiences", href: "/audiences", icon: Building2, allowedRoles: ADMIN },
      { name: "Scoring engines", href: "/engines", icon: SlidersHorizontal, allowedRoles: ADMIN },
    ],
  },
  {
    label: "Outreach",
    items: [{ name: "Drafts", href: "/drafts", icon: MailCheck, allowedRoles: ADMIN }],
  },
  {
    label: "Admin",
    items: [{ name: "Administration", href: "/admin", icon: ShieldCheck, allowedRoles: ADMIN }],
  },
];

export function visibleGroups(role: AppRole): NavGroup[] {
  return navGroups
    .map((group) => ({ ...group, items: group.items.filter((item) => item.allowedRoles.includes(role)) }))
    .filter((group) => group.items.length > 0);
}

export function isActivePath(pathname: string, href: string): boolean {
  if (pathname === href) return true;
  return href !== "/dashboard" && pathname.startsWith(`${href}/`);
}

const SEGMENT_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  leads: "Leads",
  portal: "Client portal",
  searches: "Searches",
  new: "New search",
  audiences: "Audiences",
  engines: "Scoring engines",
  drafts: "Drafts",
  admin: "Administration",
};

/** Breadcrumb labels for a pathname, e.g. /leads/abc -> ["Leads", "Lead"]. */
export function breadcrumbFor(pathname: string): string[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] === "searches" && segments[1] === "new") return ["New search"];
  return segments.map((segment, index) => {
    if (SEGMENT_LABELS[segment]) return SEGMENT_LABELS[segment];
    return index > 0 ? "Details" : segment;
  });
}

export function roleLabel(role: AppRole | undefined): string {
  switch (role) {
    case "super_admin":
      return "Super admin";
    case "org_admin":
      return "Admin";
    default:
      return "Client";
  }
}
