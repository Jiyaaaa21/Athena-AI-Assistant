/**
 * Weather page — ISSUE 7: Auto-detect user location via browser Geolocation API.
 * Falls back to manual city search. Manual override always available.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { PageHeader } from "@/components/athena/page-header";
import { EmptyState } from "@/components/athena/empty-state";
import { weatherApi } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Cloud, Droplets, Search, Thermometer, Wind, MapPin, Loader2 } from "lucide-react";

export const Route = createFileRoute("/weather")({
  head: () => ({
    meta: [
      { title: "Athena — Weather" },
      { name: "description", content: "Real-time weather intelligence for any city." },
    ],
  }),
  component: WeatherPage,
});

function WeatherPage() {
  const [city, setCity] = useState("San Francisco");
  const [query, setQuery] = useState("San Francisco");
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  // ── ISSUE 7: Auto-detect location on first load ────────────────────────────
  useEffect(() => {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          // Reverse-geocode via public API (no key needed)
          const { latitude, longitude } = pos.coords;
          const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${latitude}&lon=${longitude}&format=json`,
            { headers: { "Accept-Language": "en" } }
          );
          const data = await res.json();
          const detectedCity =
            data.address?.city ||
            data.address?.town ||
            data.address?.village ||
            data.address?.county ||
            null;
          if (detectedCity) {
            setCity(detectedCity);
            setQuery(detectedCity);
          }
        } catch {
          // silently fall back to default city
        } finally {
          setLocating(false);
        }
      },
      (err) => {
        setLocating(false);
        if (err.code !== 1) {
          // code 1 = user denied — not an error worth showing
          setLocationError("Couldn't detect your location. Search manually.");
        }
      },
      { timeout: 6000 }
    );
  }, []);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["weather", query],
    queryFn: () => weatherApi.get(query),
  });

  return (
    <div className="max-w-4xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader title="Weather Center" description="Conditions and 5-day outlook for your location." />

      {/* Search form */}
      <form
        onSubmit={(e) => { e.preventDefault(); setQuery(city); }}
        className="flex gap-2 mb-8 max-w-md"
      >
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder="Search city…"
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={locating}>
          {locating ? <Loader2 className="size-4 animate-spin" /> : "Search"}
        </Button>
        {/* Re-detect location button */}
        {navigator.geolocation && (
          <Button
            type="button"
            variant="outline"
            title="Use my location"
            onClick={() => {
              setLocating(true);
              navigator.geolocation.getCurrentPosition(
                async (pos) => {
                  try {
                    const { latitude, longitude } = pos.coords;
                    const res = await fetch(
                      `https://nominatim.openstreetmap.org/reverse?lat=${latitude}&lon=${longitude}&format=json`,
                      { headers: { "Accept-Language": "en" } }
                    );
                    const data = await res.json();
                    const detectedCity =
                      data.address?.city || data.address?.town || data.address?.village || null;
                    if (detectedCity) {
                      setCity(detectedCity);
                      setQuery(detectedCity);
                    }
                  } finally {
                    setLocating(false);
                  }
                },
                () => setLocating(false),
                { timeout: 6000 }
              );
            }}
          >
            {locating ? <Loader2 className="size-4 animate-spin" /> : <MapPin className="size-4" />}
          </Button>
        )}
      </form>

      {locationError && (
        <p className="text-xs text-muted-foreground mb-4">{locationError}</p>
      )}

      {isLoading || locating ? (
        <div className="grid md:grid-cols-3 gap-4">
          <div className="md:col-span-2 h-56 rounded-2xl bg-muted animate-pulse" />
          <div className="h-56 rounded-2xl bg-muted animate-pulse" />
        </div>
      ) : isError ? (
        <EmptyState
          icon={Cloud}
          title="Couldn't load weather"
          description="We weren't able to fetch conditions for that city."
          action={<Button onClick={() => refetch()}>Try again</Button>}
        />
      ) : data ? (
        <div className="grid md:grid-cols-3 gap-4">
          <div className="md:col-span-2 rounded-2xl border border-border bg-gradient-to-br from-primary/5 to-accent/5 p-8 ring-1 ring-black/5">
            <div className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-muted-foreground font-semibold">
              <MapPin className="size-3" />
              Current
            </div>
            <div className="mt-2 text-3xl font-semibold tracking-tight">{data.city}</div>
            <div className="mt-6 flex items-end gap-4">
              <div className="text-7xl font-semibold tracking-tighter">{data.temperatureC}°</div>
              <div className="pb-3 text-muted-foreground">{data.condition}</div>
            </div>
            <div className="mt-6 grid grid-cols-3 gap-3">
              <Stat icon={Thermometer} label="Feels like" value={`${data.feelsLikeC}°`} />
              <Stat icon={Droplets} label="Humidity" value={`${data.humidity}%`} />
              <Stat icon={Wind} label="Wind" value="12 km/h" />
            </div>
          </div>
          <div className="rounded-2xl border border-border bg-card p-5 ring-1 ring-black/5">
            <div className="text-xs uppercase tracking-widest text-muted-foreground font-semibold mb-3">5-day forecast</div>
            <ul className="space-y-3">
              {data.forecast.map((f) => (
                <li key={f.day} className="flex items-center justify-between text-sm">
                  <span className="font-medium">{f.day}</span>
                  <span className="text-muted-foreground flex items-center gap-1.5">
                    <Cloud className="size-3.5" /> {f.condition}
                  </span>
                  <span className="font-mono text-xs">{f.hi}° / {f.lo}°</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ icon: Icon, label, value }: { icon: typeof Cloud; label: string; value: string }) {
  return (
    <div className="rounded-lg bg-card/60 border border-border p-3">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground flex items-center gap-1 font-semibold">
        <Icon className="size-3" />{label}
      </div>
      <div className="text-lg font-semibold mt-1">{value}</div>
    </div>
  );
}
