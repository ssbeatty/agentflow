"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { auth } from "@/lib/api";
import type { AuthStatus } from "@/lib/types";

// Routes that render without an authenticated session.
const PUBLIC_ROUTES = ["/login", "/setup"];

/**
 * Login wall for the whole app. On every navigation it checks /api/auth/status
 * and routes the user to /setup (no admin yet), /login (not authenticated), or
 * lets them through. Children are not mounted until the user is authorized, so
 * protected pages never fire their data fetches before the session exists.
 */
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const rawPathname = usePathname();
  // next.config has trailingSlash:true, so usePathname() yields "/setup/" etc.
  // Normalize so route comparisons below match the canonical "/setup" form.
  const pathname = rawPathname !== "/" ? rawPathname.replace(/\/$/, "") : rawPathname;
  const router = useRouter();
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    auth.status()
      .then((s) => { if (!cancelled) setStatus(s); })
      // If status itself fails (server down), treat as uninitialized-ish so we
      // at least show the login page rather than a blank screen.
      .catch(() => { if (!cancelled) setStatus({ initialized: true, authenticated: false, username: null }); });
    return () => { cancelled = true; };
  }, [pathname]);

  const isPublic = PUBLIC_ROUTES.includes(pathname);

  useEffect(() => {
    if (!status) return;
    if (!status.initialized && pathname !== "/setup") {
      router.replace("/setup");
    } else if (status.initialized && !status.authenticated && !isPublic) {
      router.replace("/login");
    } else if (status.authenticated && isPublic) {
      router.replace("/");
    }
  }, [status, pathname, isPublic, router]);

  // Still resolving, or a redirect is pending → show a spinner instead of
  // flashing protected content.
  const ready =
    !!status &&
    (isPublic
      ? !status.authenticated          // public page only renders when logged out
      : status.initialized && status.authenticated);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <>{children}</>;
}
