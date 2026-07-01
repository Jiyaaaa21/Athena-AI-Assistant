/**
 * public/sw.js — Phase 21
 *
 * Minimal service worker whose only job right now is Web Push: receive a
 * push event from the browser's push service (even while no Athena tab
 * is open) and turn it into a real OS notification, then route a click
 * on that notification back into the app.
 *
 * Deliberately NOT doing offline asset caching / full PWA "app shell"
 * behavior here — that's a separate, bigger scope (and gets easy to get
 * wrong: a stale cached shell serving old JS against a migrated backend
 * schema is a worse bug than "app needs network to load"). This file is
 * push-only until that's explicitly asked for.
 */

self.addEventListener("install", () => {
  // Activate this worker as soon as it's installed, without waiting for
  // the previous one to finish controlling open tabs — there's no
  // versioned cache here to worry about invalidating.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  if (!event.data) return;

  let payload;
  try {
    payload = event.data.json();
  } catch {
    payload = { title: "Athena", body: event.data.text() };
  }

  const title = payload.title || "Athena";
  const urgent = !!payload.urgent;

  const options = {
    body: payload.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    data: { url: payload.url || "/" },
    tag: payload.tag || undefined,
    renotify: !!payload.tag,
    // Phase 23: explicit, never left to a platform default that could
    // silently be "on mute" for this origin. `silent: false` is the
    // Notifications API's own signal to play the OS's standard
    // notification sound -- Web Push has no way to ship a custom sound
    // file for a desktop notification, so this is the correct and only
    // lever available here.
    silent: false,
    // `requireInteraction: true` keeps the notification on screen until
    // the person actually dismisses or clicks it, instead of Chrome's
    // default auto-hide after a few seconds -- reserved for things
    // flagged `urgent` (overdue/high-priority reminders, an imminent
    // calendar event) so they can't be missed by glancing away for a
    // moment. Gentler proactive nudges stay auto-dismissing.
    requireInteraction: urgent,
    // Vibration only has any effect on platforms that support it
    // (mobile Chrome); harmless no-op elsewhere. Longer/insistent
    // pattern for urgent pushes vs. a single short buzz otherwise.
    vibrate: urgent ? [200, 100, 200, 100, 200] : [150],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        // Focus an existing Athena tab if one's already open, rather
        // than piling up duplicate tabs every time a notification fires.
        for (const client of clientList) {
          const clientUrl = new URL(client.url);
          if (clientUrl.origin === self.location.origin && "focus" in client) {
            client.navigate(targetUrl);
            return client.focus();
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetUrl);
        }
      })
  );
});