import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  useNavigate,
  HeadContent,
  Scripts,
  useLocation,
} from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { AppShell } from "@/components/athena/app-shell";
import { Toaster } from "@/components/ui/sonner";
import { useAuth } from "@/stores/auth";

// Routes that don't require authentication and don't show the AppShell
const AUTH_ROUTES = ["/login", "/signup", "/forgot-password"];

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Athena — AI Operating System" },
      { name: "description", content: "Athena is a premium AI workspace: chat, documents, notes, reminders, news, and memory in one elegant operating system." },
      { name: "author", content: "Athena" },
      { property: "og:title", content: "Athena — AI Operating System" },
      { property: "og:description", content: "A premium AI workspace combining chat, RAG, voice, and productivity." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      // Phase 21: PWA — installable app + status bar theming
      { name: "theme-color", content: "#2563EB" },
      { name: "mobile-web-app-capable", content: "yes" },
      { name: "apple-mobile-web-app-capable", content: "yes" },
      { name: "apple-mobile-web-app-status-bar-style", content: "black-translucent" },
      { name: "apple-mobile-web-app-title", content: "Athena" },
    ],
    links: [
      {
        rel: "preconnect",
        href: "https://fonts.googleapis.com",
      },
      {
        rel: "preconnect",
        href: "https://fonts.gstatic.com",
        crossOrigin: "anonymous",
      },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400;1,9..144,500&display=swap",
      },
      {
        rel: "stylesheet",
        href: appCss,
      },
      // Phase 21: PWA manifest + icons
      { rel: "manifest", href: "/manifest.json" },
      { rel: "icon", href: "/icons/icon-192.png" },
      { rel: "apple-touch-icon", href: "/icons/icon-192.png" },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
        {/* ISSUE 10: Inline theme init — runs before paint, prevents flash */}
        <script dangerouslySetInnerHTML={{ __html: `
          (function() {
            try {
              var theme = localStorage.getItem('athena-theme') || 'system';
              if (theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.classList.add('dark');
              } else {
                document.documentElement.classList.remove('dark');
              }
            } catch(e) {}
          })();
        `}} />
        {/* Phase 21: register the push-notification service worker. Runs
            after load so it never competes with the initial page render
            for bandwidth/CPU; registration itself is idempotent (calling
            it again just returns the existing registration), so this is
            safe to run on every full page load. */}
        <script dangerouslySetInnerHTML={{ __html: `
          if ('serviceWorker' in navigator) {
            window.addEventListener('load', function() {
              navigator.serviceWorker.register('/sw.js').catch(function() {});
            });
          }
        `}} />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function AuthGate({ children }: { children: ReactNode }) {
  const { user, initializing, initialize } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const isAuthRoute = AUTH_ROUTES.includes(location.pathname);

  // Bootstrap: try to restore session from stored refresh token (once)
  useEffect(() => {
    initialize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Phase 17 fix: navigate() must never be called directly in the render
  // body. TanStack Router's navigate() triggers a state update on the
  // router itself, and calling it synchronously while THIS component is
  // rendering is exactly what React's "Cannot update a component while
  // rendering a different component (`Transitioner`)" warning is about —
  // it was firing on every single unauthenticated-route render, which is
  // not just a console warning: under React 18/19's stricter rendering
  // guarantees this class of bug can produce genuinely inconsistent UI
  // state (a render that started under one set of props/state being
  // committed against another), which is exactly the kind of thing that
  // could intermittently break other state-dependent features on the
  // page — including voice mode, which depends on several pieces of
  // store state (auth user, settings load) being consistent before its
  // own effects fire.
  //
  // Fix: move both navigate() calls into a useEffect that runs after
  // render, gated on the same conditions. The render body now only
  // decides what to SHOW (loader, null-while-redirecting, or children) —
  // it never triggers navigation as a side effect of being rendered.
  useEffect(() => {
    if (initializing) return;
    if (!user && !isAuthRoute) {
      navigate({ to: "/login", replace: true });
    } else if (user && isAuthRoute) {
      navigate({ to: "/", replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initializing, user, isAuthRoute]);

  // While we don't know the auth state yet, show a minimal loader
  if (initializing) {
    return (
      <div className="min-h-svh flex items-center justify-center bg-background">
        <div className="size-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      </div>
    );
  }

  // Unauthenticated user trying to access a protected route — the effect
  // above will redirect; render nothing in the meantime rather than
  // flashing protected content.
  if (!user && !isAuthRoute) {
    return null;
  }

  // Authenticated user visiting an auth page — the effect above will
  // redirect to the dashboard; render nothing in the meantime.
  if (user && isAuthRoute) {
    return null;
  }

  // Auth pages get a plain wrapper (no sidebar)
  if (isAuthRoute) {
    return <>{children}</>;
  }

  // Authenticated dashboard routes get the full AppShell
  return <AppShell>{children}</AppShell>;
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <Outlet />
      </AuthGate>
      <Toaster position="top-right" />
    </QueryClientProvider>
  );
}
