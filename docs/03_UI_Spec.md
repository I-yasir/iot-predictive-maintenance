# 03 — UI Specification & Design System

Dashboard for operations engineers in control rooms (large monitors, often dark rooms) and technicians on tablets at the asset. Priorities: **state legible at a glance, color never the only signal, numbers easy to compare.**

---

## 1. Design Tokens

All tokens are CSS custom properties in `frontend/src/styles/tokens.css`. Components must not hard-code colors, sizes or fonts. Dark theme is the default; light theme via `[data-theme="light"]` and `prefers-color-scheme`.

### 1.1 Color — surfaces & text

| Token | Dark (default) | Light |
|---|---|---|
| `--bg` | `#0E1116` | `#F6F7F9` |
| `--surface-1` (cards) | `#161B22` | `#FFFFFF` |
| `--surface-2` (raised/hover) | `#1F2630` | `#EEF1F5` |
| `--border` | `#2D3540` | `#D5DAE1` |
| `--text-primary` | `#E6EAF0` | `#151A21` |
| `--text-secondary` | `#9AA5B4` | `#4F5B6B` |
| `--text-disabled` | `#5C6675` | `#9AA3AF` |
| `--accent` (links, focus, selection) | `#4C9AFF` | `#1F6FEB` |
| `--focus-ring` | `0 0 0 2px var(--accent)` | same |

### 1.2 Color — health states (semantic, fixed meaning)

| State | Token | Dark fg / bg tint | Light fg / bg tint | Icon | Label |
|---|---|---|---|---|---|
| Healthy | `--state-healthy` | `#3FB950` / `#3FB95022` | `#1A7F37` / `#1A7F3714` | ● check-circle | "Healthy" |
| Warning | `--state-warning` | `#D29922` / `#D2992222` | `#9A6700` / `#9A670014` | ▲ alert-triangle | "Warning" |
| Critical | `--state-critical` | `#F85149` / `#F8514922` | `#CF222E` / `#CF222E14` | ◆ alert-octagon | "Critical" |
| Offline | `--state-offline` | `#6E7681` / `#6E768122` | `#6E7781` / `#6E778114` | ○ wifi-off | "Offline" |
| Warming up | `--state-warming` | `#8B949E` dashed | `#8C959F` dashed | ◌ loader | "Warming up" |
| Degraded data | `--state-degraded` | `#D29922` hatched border | `#9A6700` hatched | ⚠ database-x | "Data issue" |

Rules: every state appearance = color **+ icon + text label** (WCAG 1.4.1). Text on state tints must meet 4.5:1. Critical tiles additionally get a 2 px left border and are sorted first by default.

### 1.3 Color — data visualization

- Series palette (categorical, colorblind-safe, validated in both themes): `--viz-1 #4C9AFF`, `--viz-2 #F778BA`, `--viz-3 #56D4DD`, `--viz-4 #E3B341`, `--viz-5 #A371F7`, `--viz-6 #7EE787`. Never reuse state colors for categorical series.
- Predicted RUL line: `--viz-1`; ground-truth RUL (replay only): `--text-secondary` dashed; prediction interval band: `--viz-1` at 18 % opacity.
- Threshold lines: Warning 75 and Critical 30 drawn as horizontal dashed lines in their state colors at 70 % opacity with right-aligned labels.
- Healthy baseline band on sensor charts: `--surface-2` fill with `--border` edges; anomalous points (|z| > 3) marked with `--state-warning` dots.
- Gridlines `--border` at 50 % opacity; axes text `--text-secondary` 12 px.

### 1.4 Typography

| Token | Value |
|---|---|
| `--font-sans` | `"Inter", system-ui, -apple-system, "Segoe UI", sans-serif` |
| `--font-mono` | `"JetBrains Mono", ui-monospace, monospace` (IDs, payloads, sensor codes) |
| Numerals | `font-variant-numeric: tabular-nums` on all metrics/tables |

| Role | Size / line-height / weight |
|---|---|
| `--type-display` (KPI numbers, RUL hero) | 40 / 44 / 600 |
| `--type-h1` (page title) | 24 / 32 / 600 |
| `--type-h2` (card title) | 18 / 24 / 600 |
| `--type-h3` (section label) | 14 / 20 / 600, uppercase, 0.04em tracking |
| `--type-body` | 14 / 20 / 400 |
| `--type-small` (meta, axes) | 12 / 16 / 400 |

Units are always shown next to values in `--text-secondary` (e.g., `72 cycles`, `1589.7 °R`, `47.47 psia`).

### 1.5 Spacing, radius, elevation, motion

- 4 px base grid: `--space-1 4`, `--space-2 8`, `--space-3 12`, `--space-4 16`, `--space-5 24`, `--space-6 32`, `--space-7 48`.
- Radius: `--radius-sm 4px` (chips), `--radius-md 8px` (cards), `--radius-lg 12px` (modals).
- Elevation: dark theme uses borders, not shadows; light theme `--shadow-1: 0 1px 2px rgba(0,0,0,.06), 0 1px 3px rgba(0,0,0,.1)`.
- Motion: 150 ms ease-out for hover/focus; state change on a tile = 600 ms background pulse once (disabled under `prefers-reduced-motion`). Charts do not animate on live updates (append only).

## 2. Layout & Responsive Rules

- App shell: top bar (56 px) with product name, global connection indicator (Live / Reconnecting / Offline), theme toggle; left nav rail (64 px collapsed / 220 px expanded) with Overview, Alerts, Test & Simulation, Model.
- Content max width 1600 px, 24 px gutters (16 px on < 600 px).
- 12-column CSS grid.

| Breakpoint | Width | Behavior |
|---|---|---|
| `xs` | < 600 | Nav becomes bottom tab bar; KPIs 2×2; asset list as stacked cards; charts full width 220 px tall; no horizontal page scroll |
| `sm` | 600–1023 | Nav rail collapsed; KPIs 4 across; asset grid 2 cols; detail tabs scrollable |
| `md` | 1024–1439 | Asset grid 3–4 cols + alert feed in right column (4/12) |
| `lg` | ≥ 1440 | Asset grid 5–6 cols; detail view shows Summary + Subsystems side-by-side |

Touch targets ≥ 44 × 44 px. Tables switch to cards below 600 px rather than scrolling horizontally.

## 3. Core Views

### 3.1 System Overview (`/overview`)

```
┌ KPI row ───────────────────────────────────────────────────────────┐
│ [Total 120] [● Healthy 84] [▲ Warning 25] [◆ Critical 8] [○ Off 3]│  ← each KPI clickable = filter
└────────────────────────────────────────────────────────────────────┘
┌ Filter bar: search ID · State ▾ · Profile ▾ · Source ▾ · Sort ▾ · Grid/Table toggle ┐
┌ Asset grid (8/12) ──────────────────────────┐ ┌ Right column (4/12) ──┐
│ ┌──────────────┐ ┌──────────────┐           │ │ Lowest RUL (top 5)    │
│ │◆ FD001-T034  │ │▲ FD003-T012  │  ...      │ │  bar list, RUL+band   │
│ │ RUL 18 cyc   │ │ RUL 61 cyc   │           │ ├───────────────────────┤
│ │ [10–29]      │ │ [44–80]      │           │ │ Live alert feed       │
│ │ ▁▂▃▅▇ spark  │ │ ▁▁▂▃▄ spark  │           │ │  ◆ FD001-T034 W→C 18  │
│ │ REPLAY · 2s  │ │ ESP32 · 1s   │           │ │  [Ack]                │
│ └──────────────┘ └──────────────┘           │ └───────────────────────┘
└─────────────────────────────────────────────┘
```

**Asset tile** (min 200 × 132 px): state icon+label chip, asset ID (mono), RUL hero (`--type-display` at 32 px) + "cycles", P10–P90 band text, sparkline of last 50 RUL predictions (inverted so dropping RUL trends down), source badge, last-seen relative time, flag icons (low-confidence, drift). Hover shows cycle number and health index.
**Table mode** columns: State, Asset, Profile, Source, Cycle, RUL, P10–P90, Health index, Trend (sparkline), Last seen, Flags. Sortable, sticky header, virtualized beyond 100 rows.
**Fleet RUL distribution** (collapsible card, md+): histogram of current RUL in 25-cycle bins colored by threshold region.

### 3.2 Trend & Anomaly Charts (shared components)

| Component | Spec |
|---|---|
| `RulTrendChart` | x = cycle, y = RUL (cycles, 0–max(150, data)). Predicted line + P10–P90 band + optional true RUL dashed + Warning/Critical threshold lines + alert-transition markers (vertical ticks colored by new state). Crosshair tooltip: cycle, RUL, band, health index, state. Brush to zoom; "Reset zoom" button. |
| `SensorTrendChart` | x = cycle, y = raw sensor value with unit. Shows raw points (thin, 40 % opacity), rolling mean (W=10, solid), healthy baseline band (mean ± 3σ of the first 20 cycles in the same regime), anomaly dots where |regime-normalized z| > 3. Small-multiple layout: 2 cols md, 3 cols lg, 1 col xs. Shared x-axis cursor across all small multiples. |
| `HealthGauge` | semicircle 0–1 health index; segments colored Critical (< 0.25) / Warning (0.25–0.6) / Healthy (> 0.6); numeric value in center. |
| `SubsystemBar` | horizontal bars of deviation score per subsystem (0–100), sorted descending, color by score bands (< 40 neutral `--viz-1`, 40–70 warning, > 70 critical). |
| `ContributionList` | top-3 sensors driving the latest prediction: sensor code + name + direction arrow (↑/↓ vs baseline) + contribution %. |
| `Sparkline` | 120 × 28 px, no axes, last point emphasized. |

Charts render with Recharts; each has an accessible data-table fallback (`<details>` "View data") and an `aria-label` summary such as "RUL decreased from 112 to 18 cycles over 180 cycles".

### 3.3 Component Selector & Detail Report (`/assets/:assetId`)

**Header:** breadcrumb `Overview / FD001-T034`; component selector combobox (search, grouped by state, shows RUL); state chip; source badge; profile; current cycle; last-seen; buttons "Export report", "Open printable".

**Tabs:**
1. **Summary** — RUL hero with band, HealthGauge, "Estimated failure in ~N cycles (~HH:MM at current replay/stream rate)" line, RulTrendChart (full width), latest flags with explanations, ground-truth error card (replay test units only: "Final-cycle error: +6 cycles (predicted later than true)").
2. **Sensors** — SensorTrendChart small multiples for the informative sensor set of the asset's profile (`05` §3.4), ordered by current |z| descending; toggle "Show all 21 sensors" (constant sensors are shown greyed with a "constant in this profile" note).
3. **Subsystems** — schematic strip Fan → LPC → HPC → Burner → HPT → LPT with each block colored by deviation score; SubsystemBar; per-subsystem expandable list of its sensors with current value, baseline, z-score. Persistent disclaimer: "Indicative deviation analysis, not a confirmed root cause."
4. **Alerts** — table: time, cycle, transition, RUL at transition, ack status/user; Ack action.
5. **Model** — model version, profile, training date, test RMSE/score for this profile, features used, current confidence & drift metrics with thresholds.

**Printable report** (`/assets/:id/report`): A4/Letter, light theme forced, header with asset/time/model version, summary numbers, RUL chart, top sensors table, subsystem table, alert history, footer disclaimer.

### 3.4 Test & Simulation Controls (`/test`)

- **Replay panel:** profile select, split (train/test), unit selector (multi-select / "all" / random N), speed slider (0.5–50 cycles/s, log scale), transport (MQTT/HTTP), loop toggle; Start/Pause/Resume/Stop; status chip (IDLE/RUNNING/PAUSED/COMPLETED/ERROR); counters sent/accepted/rejected/rate; progress per unit.
- **Batch evaluation card:** last run time, per-profile RMSE/score/alert confusion matrix, link to downloadable report (generated by CLI).
- **ESP32 devices panel:** device list with ID, firmware, RSSI, IP, msg rate, seq gaps, latency p50/p95, last payload (pretty JSON, mono). "Run harness checks" → checklist results (schema ✓, rate ✓, gaps ✓, latency ✓, reconnect ✓).
- **Ingest health:** accepted/rejected per minute chart, top rejection reasons, dead-letter sample viewer.
- **Setup help:** collapsible steps to flash ESP32 (link to `iot/esp32/README.md`).

## 4. Accessibility & Content Rules

- WCAG 2.2 AA contrast; visible focus ring on all interactive elements; full keyboard navigation; `aria-live="polite"` on the alert feed (critical alerts `assertive`).
- Numbers: RUL rounded to integer cycles; health index 2 decimals; sensor values to the dataset's native precision (2 decimals, 4 for s15 BPR / s21 W32 / settings).
- Relative times ("2 s ago") with absolute time in tooltip, in the viewer's local timezone.
- Language: plain verbs ("Acknowledge", "Start replay"); never show raw stack traces.
