"""Central search configuration — single source of truth for all sources.

Edit values here to retune the search; no need to touch source adapters.
"""

# --- WHAT to look for ---------------------------------------------------------
# "prodej" (sale) or "pronajem" (rent). One or the other per bot; run a second
# copy of the bot if you want both.
OFFER_TYPE = "prodej"

# Property categories to scrape: any of "byty", "domy", "chaty", "pozemky".
# Rent is rare for "chaty" and "pozemky"; a portal with none just returns nothing.
PROPERTY_TYPES: list[str] = ["byty", "domy", "chaty"]

# Empty list = all dispositions. Applies to "byty" only — houses, cottages and
# land are never filtered by it.
DISPOSITIONS: list[str] = []

# Max price in CZK: the sale price, or the MONTHLY rent when OFFER_TYPE is
# "pronajem" (fees not included). None = no upper limit.
MAX_PRICE_CZK: int | None = 6_000_000

# Min usable area in m² for "byty", "domy" and "chaty". None = no lower limit.
# Unknown area is kept.
MIN_AREA_M2: int | None = 40

# Min plot area in m² for "pozemky" (their area is the whole plot, so it gets its
# own limit). None = no lower limit. Unknown area is kept.
MIN_LAND_AREA_M2: int | None = None

# --- WHERE to look ------------------------------------------------------------
# Sreality okres (district) slugs — coarse net, refined to radius via GPS below.
OKRESY = ["pisek"]

# Bezrealitky regional listing (kraj slug in URL).
BEZREALITKY_KRAJ = "jihocesky-kraj"

# Search center (Písek) + radius for precise geo refinement.
CENTER_LAT = 49.3088
CENTER_LON = 14.1475
CENTER_NAME = "Písku"              # grammar in emails: "km od Písku"
SEARCH_AREA_LABEL = "Písek"        # short label in subject line
RADIUS_KM = 15.0

# iDNES Reality has NO coordinates in listings, so it can't use the GPS radius.
# Instead we fetch these okres pages and keep only listings whose town is in
# TOWNS_NEAR — a static allowlist approximating the target area.
IDNES_OKRESY = ["okres-pisek"]
TOWNS_NEAR = [
    "Písek",
]

# --- Nice-to-have flags (not filters, just highlighted in the report) ---------
HIGHLIGHT_BALCONY = True
HIGHLIGHT_PARKING = True

# --- Delivery -----------------------------------------------------------------
# Fallback recipients if REPORT_RECIPIENT env var is not set.
# Keep this empty and set REPORT_RECIPIENT in .env (local) / GitHub Secrets (CI)
# so no e-mail address ever ends up in the repository.
RECIPIENT_EMAILS: list[str] = []
SEND_TIME_LOCAL = "07:00"           # informational; real schedule lives in CI cron
