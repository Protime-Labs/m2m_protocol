# M2M Fleet Console (web)

The hosted single pane of glass for AATA-governed agent fleets — an Intune-style admin
center over the Supabase console backend (see `aata_prototype/console/README.md` for the
estate side). **Read-only v1**: monitor, drill down, report; governance *actions* are a
gated follow-on. Enforcement never depends on this app.

Next.js (App Router, TypeScript) + `@supabase/supabase-js`. Auth: Supabase email/password;
reads are enforced by RLS (authenticated-only), so the UI gate is UX, not the boundary.

## Panes

- **Dashboard** — posture strip (denials/IOCs/quarantined/feed health), KPI tiles per
  posture, attention-needed grid, live event ticker (Realtime).
- **Agents** — live roster: an agent appears the moment its W2 birth event lands.
  Liveness dot (wall-clock), posture pill, assurance badge (crypto- vs software-attested —
  weaker assurance is shown, never hidden). Click through to the agent page:
  **Overview** (identity, envelope, honesty notes) · **Activity graph** (the clickable,
  explorable SVG: agent → calls → evidence → IOCs → hygiene; click any node for its full
  payload) · **Events** (timeline with payload expansion).
- **Detections** — IOCs, W3 hygiene responses, and semantic-judge entries categorized
  **recorded, not adjudicated** (spec 10.1: surfaced, never shown as clean, never enforced).
- **Evidence** — the C9 record mirror with kind/agent filters (correlate back to the
  estate's hash chain via `seq`/`t`).
- **Reports** — fleet posture distribution + denials by cause, backed by the SQL views.

## Run locally

```bash
cp .env.local.example .env.local     # fill in your Supabase URL + publishable key
npm install
npm run dev                          # http://localhost:3000
```

Sign in with a Supabase Auth user (provision via the Supabase dashboard → Authentication).

## Deploy to Vercel

1. Import the `m2m_protocol` repo in Vercel; set **Root Directory** = `console-web`.
2. Environment variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   (both public-safe; data access is gated by Auth + RLS).
3. Deploy. In Supabase → Authentication → URL Configuration, add the Vercel domain to
   the allowed redirect/site URLs.

## Feed it

Any estate publishes with three env vars and one line of wiring — see
[`aata_prototype/console/README.md`](../aata_prototype/console/README.md). To demo:
run the Sprint-2 smoke pattern (mixed honest/covert/revoked estate) and watch agents
appear, drift, and get quarantined live.
