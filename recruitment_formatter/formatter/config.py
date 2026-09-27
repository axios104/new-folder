"""
Central schema configuration.

Everything about "what the correct format looks like" lives here. If a new
source file uses a header spelling you haven't seen, add it to ALIASES —
no other code needs to change.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class FieldSpec:
    # Canonical output name (matches your reference Excel exactly)
    output_name: str
    # snake_case key used internally / in JSON / for Zoho payloads
    key: str
    # Known header spellings seen across employees' sheets (lowercase, stripped)
    aliases: tuple[str, ...]
    # Data type used for cleaning/coercion
    dtype: str = "str"  # one of: str, int, float, currency, phone, url
    required: bool = False
    # Zoho CRM API field name (module: Contacts / custom module). None = not pushed.
    zoho_field: Optional[str] = None


# ---------------------------------------------------------------------------
# CANONICAL SCHEMA - derived from the reference file (Agent_Vinod.xlsx)
# Column order here == column order in every output file.
# ---------------------------------------------------------------------------
SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec(
        output_name="Name", key="name", dtype="str", required=True,
        zoho_field="Last_Name",
        aliases=(
            "name", "agent name", "agent_name", "full name", "fullname",
            "agent", "consultant name", "consultant_name", "employee name",
            "name of the client", "name of client", "client name",
            "customer name", "contact name", "candidate name", "person name",
        ),
    ),
    FieldSpec(
        output_name="job_title", key="job_title", dtype="str",
        zoho_field="Title",
        aliases=(
            "job_title", "job title", "designation", "role", "position",
            "title",
        ),
    ),
    FieldSpec(
        output_name="Years_experience", key="years_experience", dtype="int",
        zoho_field="Years_Of_Experience",
        aliases=(
            "years_experience", "years experience", "experience",
            "years of experience", "yrs_experience", "exp", "yoe",
        ),
    ),
    FieldSpec(
        output_name="Agency Name", key="agency_name", dtype="str",
        zoho_field="Company",
        aliases=(
            "agency name", "agency_name", "agency", "company",
            "company name", "firm", "firm name", "organisation",
            "organization", "name of organisation", "name of organization",
            "organisation name", "organization name", "org name",
            "employer", "employer name", "business name",
        ),
    ),
    FieldSpec(
        output_name="Email ID of the Agent", key="agent_email", dtype="str",
        zoho_field="Email",
        aliases=(
            "email id of the agent", "email", "email id", "email_id",
            "agent email", "agent_email", "e-mail", "mail id",
            "email address",
        ),
    ),
    FieldSpec(
        output_name="suburbs", key="suburb", dtype="str",
        zoho_field="City",
        aliases=(
            "suburbs", "suburb", "area", "locality", "region", "city",
            "location", "town", "place",
        ),
    ),
    FieldSpec(
        output_name="Post code", key="postcode", dtype="str",
        zoho_field="Zip_Code",
        aliases=(
            "post code", "postcode", "post_code", "zip", "zip code",
            "zipcode", "pin code", "pincode",
        ),
    ),
    FieldSpec(
        output_name="agency_address", key="agency_address", dtype="str",
        zoho_field="Mailing_Street",
        aliases=(
            "agency_address", "agency address", "address", "office address",
            "street address", "full address",
        ),
    ),
    FieldSpec(
        output_name="phone", key="phone", dtype="phone",
        zoho_field="Phone",
        aliases=(
            "phone", "phone number", "phone_number", "mobile",
            "mobile number", "contact", "contact number", "contact_number",
            "cell", "tel", "phone no", "phone no.", "ph no", "ph. no",
            "contact no", "contact no.", "mobile no", "telephone",
            "telephone number",
        ),
    ),
    FieldSpec(
        output_name="rating", key="rating", dtype="float",
        zoho_field="Rating",
        aliases=("rating", "star rating", "stars", "agent rating", "score"),
    ),
    FieldSpec(
        output_name="properties_sold", key="properties_sold", dtype="int",
        zoho_field="Properties_Sold",
        aliases=(
            "properties_sold", "properties sold", "sold", "total sold",
            "no of properties sold", "no_of_properties_sold", "sales count",
        ),
    ),
    FieldSpec(
        output_name="median_sold_price", key="median_sold_price", dtype="currency",
        zoho_field="Median_Sold_Price",
        aliases=(
            "median_sold_price", "median sold price", "median price",
            "avg sold price", "average sold price", "median sale price",
        ),
    ),
    FieldSpec(
        output_name="median_days_advertised", key="median_days_advertised", dtype="int",
        zoho_field="Median_Days_Advertised",
        aliases=(
            "median_days_advertised", "median days advertised",
            "days advertised", "median dom", "days on market",
            "avg days advertised",
        ),
    ),
    FieldSpec(
        output_name="profile_url", key="profile_url", dtype="url",
        zoho_field="Profile_URL",
        aliases=(
            "profile_url", "profile url", "agent url", "agent_url",
            "agent link", "profile link", "profile",
        ),
    ),
    FieldSpec(
        output_name="agency_url", key="agency_url", dtype="url",
        zoho_field="Agency_URL",
        aliases=(
            "agency_url", "agency url", "agency link", "company url",
            "company_url", "agency page",
        ),
    ),
)

FIELD_BY_KEY = {f.key: f for f in SCHEMA}
OUTPUT_COLUMNS = [f.output_name for f in SCHEMA]


def _check_no_duplicate_aliases() -> None:
    """
    Fails fast at import time if the same alias string is assigned to two
    different fields — such a collision silently corrupts header mapping
    (last-defined field wins) with no error, so this is checked eagerly
    instead of being left to show up as a mystery mis-mapped column later.
    """
    seen: dict[str, str] = {}
    for spec in SCHEMA:
        for alias in (spec.output_name, *spec.aliases):
            norm = alias.strip().lower()
            if norm in seen and seen[norm] != spec.key:
                raise ValueError(
                    f"Duplicate alias '{alias}' assigned to both "
                    f"'{seen[norm]}' and '{spec.key}' in SCHEMA. "
                    "An alias must belong to exactly one field."
                )
            seen[norm] = spec.key


_check_no_duplicate_aliases()

# Fuzzy-match confidence floor (0-1). Below this, a header is left unmatched
# and reported, rather than silently guessed.
FUZZY_MATCH_THRESHOLD = 0.72

# Value used to fill genuinely missing data (some source files lack fields
# entirely per your description of "totally inconsistent" sheets).
MISSING_VALUE = ""

# ---------------------------------------------------------------------------
# Zoho CRM settings — module name and dedup key for upserts.
# ---------------------------------------------------------------------------
ZOHO_MODULE = "Contacts"          # e.g. "Contacts", "Leads", or a custom module "Agents"
ZOHO_DUPLICATE_CHECK_FIELD = "Email"  # field Zoho uses to detect duplicates on upsert
