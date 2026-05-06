# Magari Scout — Implementation Plan

Repurpose the Dalali Scout real estate scraper into a **used car seller discovery and listing extraction tool** for the Tanzanian Instagram market.

## Goal

Scrape Instagram for Tanzanian used car sellers using keywords like **magari**, **motor**, **tanzania**, **used** — extract structured vehicle listing data from their posts, and output reports in Excel and HTML.

---

## Phase 1: Configuration Changes

### 1.1 Replace area/tier config with car market segments

**File: `config/areas.ts`**

Replace the neighborhood-based tiers with car market segments:

```typescript
export const TIER_AREAS: Record<string, string[]> = {
  luxury: ["Land Cruiser", "Range Rover", "Mercedes", "BMW", "Lexus", "Porsche"],
  midrange: ["Toyota", "Honda", "Nissan", "Mazda", "Mitsubishi", "Subaru"],
  budget: ["Suzuki", "Daihatsu", "Vitz", "Probox", "Fielder", "Ractis"],
  trucks: ["Canter", "Dyna", "Hilux", "L200", "pickup", "truck"],
  buses: ["Coaster", "Rosa", "Hiace", "Noah", "bus", "van"],
};
```

### 1.2 Update search queries

**File: `config/areas.ts` — `buildQueries()` function**

Replace real estate queries with car-focused queries:

```
"magari {segment}"
"motor {segment}"
"gari {segment}"
"used cars {segment}"
"magari ya kuuza {segment}"
"cars tanzania {segment}"
"gari la kuuza {segment}"
"magari dar es salaam"
```

### 1.3 Replace neighborhoods config with location/showroom data

**File: `config/neighborhoods.ts`**

Replace `KNOWN_NEIGHBORHOODS` with known car market locations in Tanzania:

```
Manzese, Ubungo, Kariakoo, City Centre, Tegeta, Mbezi, Kibaha,
Tabata, Sinza, Mikocheni, Pugu Road, Bagamoyo Road, etc.
```

Also add known car dealer market areas like **Manzese auto market**, **Kariakoo**, etc.

---

## Phase 2: Data Model Changes

### 2.1 Update the listings table schema

**File: `db/migrate.ts`**

Replace the real estate schema with a vehicle schema:

```sql
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date_found TEXT DEFAULT (datetime('now')),
  post_date TEXT,
  likes INTEGER,

  -- Vehicle fields
  listing_type TEXT,          -- "For Sale", "Wanted", ""
  vehicle_type TEXT,          -- "Sedan", "SUV", "Pickup", "Van", "Bus", "Truck", "Motorcycle", ""
  make TEXT,                  -- "Toyota", "Honda", "Mercedes", etc.
  model TEXT,                 -- "Land Cruiser", "Civic", "C-Class", etc.
  year INTEGER,               -- Manufacturing year
  mileage_km INTEGER,         -- Mileage in kilometers
  transmission TEXT,          -- "Automatic", "Manual", ""
  fuel_type TEXT,             -- "Petrol", "Diesel", "Hybrid", "Electric", ""
  engine_cc INTEGER,          -- Engine displacement in cc
  color TEXT,
  condition TEXT,             -- "New", "Used", "Accident-free", ""
  location TEXT,              -- Raw location text
  region TEXT,                -- Cleaned region/area

  -- Pricing
  price_original TEXT,        -- Raw price string from caption
  price_tsh INTEGER,          -- Normalized price in TSH
  price_usd REAL,             -- Price in USD if listed that way
  currency TEXT,              -- "TSH", "USD", null
  negotiable TEXT,            -- "Negotiable", "Fixed", ""

  -- Extras
  features TEXT,              -- Comma-separated: AC, leather seats, sunroof, etc.
  contact TEXT,               -- Phone number(s)
  tags TEXT,                  -- Hashtags
  duty_status TEXT,           -- "Duty Paid", "Duty Not Paid", ""

  -- Source
  source_account TEXT,
  post_url TEXT UNIQUE,
  media_type TEXT,
  display_url TEXT,
  video_url TEXT,
  images TEXT,
  caption_raw TEXT,
  summary TEXT,
  run_id TEXT
);
```

### 2.2 Update the accounts table

**File: `db/migrate.ts`**

Change `tier` and `area` to reflect car market segments:

```sql
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  segment TEXT,              -- "luxury", "midrange", "budget", "trucks", "buses"
  specialization TEXT,       -- "Toyota specialist", "imported cars", etc.
  confidence TEXT,
  followers INTEGER,
  discovered_at TEXT DEFAULT (datetime('now')),
  last_scraped TEXT
);
```

### 2.3 Update TypeScript types

**File: `types.ts`**

- Replace the `Listing` interface fields to match the new schema
- Replace `affordability_tier` logic with car price tiers:
  - Budget: < 10M TSH
  - Mid-Range: 10M - 30M TSH
  - Upper Mid-Range: 30M - 80M TSH
  - Luxury: > 80M TSH
- Replace `AMENITY_PATTERNS` with `FEATURE_PATTERNS`:

```typescript
export const FEATURE_PATTERNS: Record<string, RegExp> = {
  ac: /\bAC\b|air.?condition/i,
  leather_seats: /leather|ngozi/i,
  sunroof: /sunroof|sun.?roof/i,
  alloy_wheels: /alloy|mags|rims/i,
  reverse_camera: /reverse.?cam|back.?cam|camera/i,
  bluetooth: /bluetooth|BT/i,
  navigation: /navi|GPS/i,
  cruise_control: /cruise.?control/i,
  parking_sensors: /parking.?sensor/i,
  turbo: /turbo|turbocharged/i,
  four_wd: /4WD|4x4|AWD|four.?wheel/i,
  roof_rack: /roof.?rack/i,
  bull_bar: /bull.?bar|bumper.?guard/i,
  tinted_windows: /tint/i,
  fog_lights: /fog.?light/i,
};
```

---

## Phase 3: AI Prompt Changes

### 3.1 Create car extraction prompt

**File: `skills/categorize.md`**

Replace the real estate extraction prompt entirely. The new prompt should:

- Instruct Claude to extract vehicle data from Instagram captions
- Handle Swahili car terminology:
  - `"gari"` / `"magari"` = car(s)
  - `"la kuuza"` / `"inauzwa"` = for sale
  - `"mwendo"` = mileage/drive
  - `"mfumo"` = system/transmission
  - `"bei"` = price
  - `"milioni"` / `"ML"` / `"M"` = millions
  - `"laki"` = hundred thousand
  - `"duty paid"` / `"DP"` = import duty paid
  - `"duty not paid"` / `"DNP"` = needs duty payment
- Return structured JSON matching the new schema:

```json
{
  "listing_type": "For Sale",
  "vehicle_type": "SUV",
  "make": "Toyota",
  "model": "Land Cruiser Prado",
  "year": 2018,
  "mileage_km": 45000,
  "transmission": "Automatic",
  "fuel_type": "Diesel",
  "engine_cc": 2800,
  "color": "White",
  "condition": "Used",
  "location": "Dar es Salaam, Manzese",
  "region": "Manzese",
  "price_original": "ML 85",
  "price_tsh": 85000000,
  "price_usd": null,
  "currency": "TSH",
  "negotiable": "Negotiable",
  "features": "AC, leather seats, sunroof, 4WD, reverse camera",
  "contact": "+255 712 345 678",
  "duty_status": "Duty Paid",
  "tags": "#magari #toyota #landcruiser",
  "summary": "2018 Toyota Land Cruiser Prado, diesel automatic, 45K km, duty paid, white, fully loaded with AC/leather/sunroof, TSH 85M negotiable in Manzese"
}
```

- Return `null` for non-vehicle posts (ads, memes, greetings)

### 3.2 Update account validation prompt

**File: `inngest/functions/discoverAccounts.ts`**

Change the Claude Opus validation prompt to identify car dealer accounts instead of property agents. Look for signals like:

- Bio mentions: magari, cars, motors, vehicles, auto, dealer, showroom
- Consistent car-related content in username or bio
- High follower engagement on vehicle posts

---

## Phase 4: Triage System Updates

### 4.1 Update critical fields

**File: `services/triage.ts`**

Change critical fields from `["price_tsh", "bedrooms", "neighborhood"]` to:

```typescript
const CRITICAL_FIELDS = ["price_tsh", "make", "model"];
```

### 4.2 Update triage agent tools

**File: `mastra/agents/triageAgent.ts`**

Update the triage agent's instructions to focus on car data recovery.

**File: `mastra/tools/lookupNeighborhoodTool.ts`**

Rename to `lookupRegionTool.ts` — fuzzy-match car dealer locations against known Tanzanian areas instead of Dar es Salaam neighborhoods.

**File: `mastra/tools/reExtractTool.ts`**

Update the re-extraction hints to focus on car-specific patterns (e.g., "focus on MILIONI price format", "look for year near make/model", "check for CC engine size").

---

## Phase 5: Output Updates

### 5.1 Update Excel report

**File: `services/excel.ts`**

Replace the 4 sheets:

1. **All Listings** — All vehicle fields, color-coded by price tier
2. **Price Analysis** — Pivot tables:
   - By make: count, avg/min/max price
   - By vehicle type: count, avg/min/max price
   - By year range: count, avg/min/max price
3. **Features Matrix** — Binary columns per feature (AC, leather, sunroof, 4WD, etc.)
4. **Needs Review** — Triage queue items

Update tier colors:
- Budget (< 10M): light green
- Mid-Range (10M-30M): light blue
- Upper Mid-Range (30M-80M): light yellow
- Luxury (> 80M): light pink

### 5.2 Update HTML template

**File: `templates/template.eta`**

- Replace property cards with vehicle cards showing: make, model, year, price, mileage, transmission, fuel type, duty status
- Update filters: by make, vehicle type, price tier, year range
- Update summary breakdown table

### 5.3 Update email notifications

**File: `services/email.ts`**

Change email subject and content to reference car listings instead of property listings.

---

## Phase 6: CLI Updates

### 6.1 Update agent.ts prompts

**File: `agent.ts`**

- Change tier labels from neighborhood tiers to car segments: "luxury", "midrange", "budget", "trucks", "buses"
- Update CLI prompts: "Select vehicle segments to search"
- Update terminal summary to show: make x price tier breakdown

### 6.2 Update utility scripts

- **`scripts/stats.ts`** — Change statistics queries to vehicle-relevant breakdowns
- **`scripts/export-csv.ts`** — Update column headers for vehicle fields
- **`scripts/review.ts`** — No major changes needed (generic review queue display)

---

## Phase 7: Analysis Scripts

### 7.1 Update quality audit

**File: `analysis/quality-audit.ts`**

Audit vehicle extraction quality: check for missing make/model, unreasonable prices, invalid years, etc.

### 7.2 Update core analytics

**File: `analysis/core-analytics.ts`**

Replace real estate analytics with car market analytics:
- Price distribution by make
- Most common models
- Average mileage by year
- Duty paid vs unpaid ratio
- Price trends by segment

---

## Implementation Order

Follow this order when implementing with Claude Code. Each step should be a working state.

### Step 1 — Database and types (foundation)
1. Update `types.ts` with new interfaces, price tiers, and feature patterns
2. Update `db/migrate.ts` with new schema (drop old tables or create a fresh DB)
3. Run `deno task db:migrate` to verify

### Step 2 — Configuration
4. Update `config/areas.ts` with car segments and search queries
5. Update `config/neighborhoods.ts` to car market locations (rename to `config/locations.ts`)

### Step 3 — AI prompts
6. Rewrite `skills/categorize.md` for car extraction
7. Update account validation prompt in `inngest/functions/discoverAccounts.ts`

### Step 4 — Core pipeline
8. Update `inngest/functions/scrapeAndCategorize.ts` to use new schema fields
9. Update `services/triage.ts` critical fields
10. Update triage tools (`reExtractTool.ts`, `lookupNeighborhoodTool.ts` -> `lookupRegionTool.ts`, `flagForReviewTool.ts`)
11. Update `mastra/agents/triageAgent.ts`

### Step 5 — Output
12. Update `services/excel.ts` with vehicle-specific sheets and analysis
13. Update `templates/template.eta` for vehicle cards and filters
14. Update `services/html.ts` if any code changes needed beyond the template
15. Update `services/email.ts` for car-related messaging

### Step 6 — CLI and scripts
16. Update `agent.ts` CLI prompts and summary output
17. Update `scripts/stats.ts`, `scripts/export-csv.ts`

### Step 7 — Analysis
18. Update `analysis/quality-audit.ts` and `analysis/core-analytics.ts`

### Step 8 — Test end-to-end
19. Run `deno task start` in interactive mode
20. Select one segment (e.g., "midrange")
21. Verify: discovery finds car accounts, scraping extracts posts, Claude returns valid vehicle JSON, Excel/HTML output looks correct
22. Run `deno task db:stats` to verify data

---

## Key Swahili Car Terms Reference

| Swahili | English |
|---------|---------|
| magari | cars |
| gari | car |
| kuuza / inauzwa | to sell / for sale |
| bei | price |
| milioni / ML | million |
| laki | hundred thousand |
| mwendo | mileage/drive |
| injini | engine |
| mfumo | system (transmission) |
| rangi | color |
| nyeupe | white |
| nyeusi | black |
| mzigo | cargo/load |
| pikipiki | motorcycle |
| basi | bus |
| lori | truck/lorry |
| DP / duty paid | import duty paid |
| DNP | duty not paid |
| CC | engine displacement |
| gear moja moja | manual transmission |
| automatic / auto | automatic transmission |

---

## Notes

- The Apify token, Anthropic API key, and Resend API key remain the same — no new services needed
- The project structure stays identical — only file contents change
- Instagram search queries are the most important tuning point for discovery quality
- Consider adding the query `"showroom"` and `"dealer"` alongside the Swahili terms
- Duty status (paid/unpaid) is a critical field for Tanzanian car buyers — make sure the extraction prompt handles it well

