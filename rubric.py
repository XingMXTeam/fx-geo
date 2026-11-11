"""geo-optimizer 4.19 score rubric.

Copied from Auriti-Labs/geo-optimizer-skill v4.19.0
``src/geo_optimizer/models/config.py`` (``DEFAULT_SCORE_VERSION = 2``).
Category maxima are the whole scale: v1 and v2 are both 100 points and are not
convertible. A stored category max is never rewritten onto the other scale.
"""
from __future__ import annotations

UPSTREAM = "Auriti-Labs/geo-optimizer-skill v4.19.0"
DEFAULT_SCORE_VERSION = 2
HYGIENE_NOTE = "卫生分不是 AI 引用率、提及率或发现率。"

# 4.18.3 / rubric v1 check keys in the audit JSON. v2 adds google_ai.
CHECK_KEYS = {
    "robots_txt": "robots",
    "llms_txt": "llms",
    "schema_jsonld": "schema",
    "meta_tags": "meta",
    "content": "content",
    "signals": "signals",
    "ai_discovery": "ai_discovery",
    "brand_entity": "brand_entity",
}

CATEGORY_ORDER_V1 = [
    "robots", "llms", "schema", "meta", "content", "signals", "ai_discovery", "brand_entity",
]
CATEGORY_ORDER_V2 = [
    "google_ai", "robots", "schema", "content", "brand_entity", "meta", "llms", "signals", "ai_discovery",
]

CATEGORY_MAX_V1 = {
    "robots": 18,
    "llms": 18,
    "schema": 16,
    "meta": 14,
    "content": 12,
    "brand_entity": 10,
    "signals": 6,
    "ai_discovery": 6,
}
CATEGORY_MAX_V2 = {
    "google_ai": 20,
    "robots": 14,
    "schema": 14,
    "content": 14,
    "brand_entity": 12,
    "meta": 11,
    "llms": 6,
    "signals": 6,
    "ai_discovery": 3,
}

# Signal weights. Zeros are real: v2 drops those points instead of renaming them.
SCORING_V1 = {
    "robots_found": 5,
    "robots_citation_ok": 13,
    "llms_found": 5,
    "llms_h1": 2,
    "llms_blockquote": 1,
    "llms_sections": 2,
    "llms_links": 2,
    "llms_depth": 2,
    "llms_depth_high": 2,
    "llms_full": 2,
    "schema_any_valid": 2,
    "schema_richness": 3,
    "schema_faq": 3,
    "schema_article": 3,
    "schema_organization": 3,
    "schema_website": 2,
    "schema_sameas": 0,
    "meta_title": 5,
    "meta_description": 2,
    "meta_canonical": 3,
    "meta_og": 4,
    "content_h1": 2,
    "content_numbers": 1,
    "content_links": 1,
    "content_word_count": 2,
    "content_heading_hierarchy": 2,
    "content_lists_or_tables": 2,
    "content_front_loading": 2,
    "signals_lang": 3,
    "signals_rss": 2,
    "signals_freshness": 1,
    "ai_discovery_well_known": 2,
    "ai_discovery_summary": 2,
    "ai_discovery_faq": 1,
    "ai_discovery_service": 1,
    "brand_entity_coherence": 3,
    "brand_kg_readiness": 3,
    "brand_about_contact": 2,
    "brand_geo_identity": 1,
    "brand_topic_authority": 1,
}
SCORING_V2 = {
    "robots_found": 3,
    "robots_citation_ok": 11,
    "llms_found": 3,
    "llms_h1": 0,
    "llms_blockquote": 0,
    "llms_sections": 1,
    "llms_links": 1,
    "llms_depth": 0,
    "llms_depth_high": 0,
    "llms_full": 1,
    "schema_any_valid": 2,
    "schema_richness": 2,
    "schema_faq": 2,
    "schema_article": 2,
    "schema_organization": 3,
    "schema_website": 1,
    "schema_sameas": 0,
    "schema_visible_match": 2,
    "meta_title": 5,
    "meta_description": 2,
    "meta_canonical": 0,
    "meta_og": 4,
    "content_h1": 2,
    "content_numbers": 1,
    "content_links": 1,
    "content_word_count": 1,
    "content_heading_hierarchy": 3,
    "content_lists_or_tables": 2,
    "content_front_loading": 2,
    "content_images_alt": 2,
    "signals_lang": 3,
    "signals_rss": 1,
    "signals_freshness": 2,
    "ai_discovery_well_known": 1,
    "ai_discovery_summary": 1,
    "ai_discovery_faq": 0,
    "ai_discovery_service": 0,
    "ai_discovery_markdown": 1,
    "brand_entity_coherence": 3,
    "brand_kg_readiness": 4,
    "brand_about_contact": 3,
    "brand_geo_identity": 1,
    "brand_topic_authority": 1,
}
ROBOTS_PARTIAL_SCORE_V1 = 10
ROBOTS_PARTIAL_SCORE_V2 = 8
GOOGLE_AI_POINTS = {
    "G-INDEX": 5,
    "G-SNIPPET": 5,
    "G-CANONICAL": 3,
    "G-DATES": 2,
    "G-BYLINE": 2,
    "G-LINKS": 1,
    "G-VIEWPORT": 1,
    "G-SITEMAP": 1,
    "G-GENAI-CONTROL": 0,
}

CATEGORY_MAX_BY_VERSION = {1: CATEGORY_MAX_V1, 2: CATEGORY_MAX_V2}
SCORING_BY_VERSION = {1: SCORING_V1, 2: SCORING_V2}


def _line(pairs: list[tuple[str, int]]) -> str:
    return " · ".join(f"{name} {points}" for name, points in pairs)


# Display lines list every signal, including dropped zeros, so the panel
# shows the v2 cuts instead of a shortened hybrid.
CATEGORY_SIGNAL_PARTS_V2 = {
    "google_ai": [(key, GOOGLE_AI_POINTS[key]) for key in GOOGLE_AI_POINTS],
    "robots": [("found", SCORING_V2["robots_found"]), ("citation bots allowed", SCORING_V2["robots_citation_ok"])],
    "schema": [
        ("any valid", SCORING_V2["schema_any_valid"]),
        ("richness", SCORING_V2["schema_richness"]),
        ("FAQ", SCORING_V2["schema_faq"]),
        ("Article", SCORING_V2["schema_article"]),
        ("Organization", SCORING_V2["schema_organization"]),
        ("WebSite", SCORING_V2["schema_website"]),
        ("sameAs", SCORING_V2["schema_sameas"]),
        ("visible name match", SCORING_V2["schema_visible_match"]),
    ],
    "content": [
        ("H1", SCORING_V2["content_h1"]),
        ("numbers", SCORING_V2["content_numbers"]),
        ("links", SCORING_V2["content_links"]),
        ("word count", SCORING_V2["content_word_count"]),
        ("heading hierarchy", SCORING_V2["content_heading_hierarchy"]),
        ("lists/tables", SCORING_V2["content_lists_or_tables"]),
        ("front-loading", SCORING_V2["content_front_loading"]),
        ("image alt", SCORING_V2["content_images_alt"]),
    ],
    "brand_entity": [
        ("coherence", SCORING_V2["brand_entity_coherence"]),
        ("KG readiness", SCORING_V2["brand_kg_readiness"]),
        ("about/contact", SCORING_V2["brand_about_contact"]),
        ("geo identity", SCORING_V2["brand_geo_identity"]),
        ("topic authority", SCORING_V2["brand_topic_authority"]),
    ],
    "meta": [
        ("title", SCORING_V2["meta_title"]),
        ("description", SCORING_V2["meta_description"]),
        ("canonical", SCORING_V2["meta_canonical"]),
        ("Open Graph", SCORING_V2["meta_og"]),
    ],
    "llms": [
        ("found", SCORING_V2["llms_found"]),
        ("h1", SCORING_V2["llms_h1"]),
        ("blockquote", SCORING_V2["llms_blockquote"]),
        ("sections", SCORING_V2["llms_sections"]),
        ("links", SCORING_V2["llms_links"]),
        ("depth", SCORING_V2["llms_depth"]),
        ("depth_high", SCORING_V2["llms_depth_high"]),
        ("llms-full", SCORING_V2["llms_full"]),
    ],
    "signals": [
        ("lang", SCORING_V2["signals_lang"]),
        ("RSS", SCORING_V2["signals_rss"]),
        ("freshness", SCORING_V2["signals_freshness"]),
    ],
    "ai_discovery": [
        ("ai.txt", SCORING_V2["ai_discovery_well_known"]),
        ("summary.json", SCORING_V2["ai_discovery_summary"]),
        ("faq.json", SCORING_V2["ai_discovery_faq"]),
        ("service.json", SCORING_V2["ai_discovery_service"]),
        ("markdown negotiation", SCORING_V2["ai_discovery_markdown"]),
    ],
}
CATEGORY_SIGNAL_LINES_V2 = {
    key: _line(CATEGORY_SIGNAL_PARTS_V2[key]) for key in CATEGORY_ORDER_V2
}


def parse_score_version(value) -> int:
    """Missing and legacy values stay on v1. Only an explicit 2 is v2."""
    if value in (2, "2", "v2", "V2"):
        return 2
    return 1


def category_max(score_version) -> dict:
    return dict(CATEGORY_MAX_BY_VERSION[parse_score_version(score_version)])


def check_max(score_version) -> dict:
    """Maxima keyed the way audit JSON names checks. v2 also includes google_ai."""
    version = parse_score_version(score_version)
    maxima = CATEGORY_MAX_BY_VERSION[version]
    out = {check: maxima[cat] for check, cat in CHECK_KEYS.items()}
    if version == 2:
        out["google_ai"] = maxima["google_ai"]
    return out


# Live default for new samples. Historical 4.18.3 rows must use check_max(1).
CHECK_MAX = check_max(DEFAULT_SCORE_VERSION)


def normalize_breakdown(raw, score_version) -> dict:
    """Attach a max only when the stored cell does not already have one.

    A stored max is the rubric that produced the score. It is not replaced
    with the other version's max.
    """
    if not isinstance(raw, dict):
        return {}
    maxes = category_max(score_version)
    out = {}
    for key, cell in raw.items():
        if key == "negative_penalty":
            out[key] = cell
            continue
        if isinstance(cell, bool):
            continue
        if isinstance(cell, (int, float)):
            if key in maxes:
                out[key] = {"score": cell, "max": maxes[key]}
            continue
        if isinstance(cell, dict) and isinstance(cell.get("score"), (int, float)) and not isinstance(cell.get("score"), bool):
            stored = cell.get("max")
            if isinstance(stored, (int, float)) and not isinstance(stored, bool):
                out[key] = {"score": cell["score"], "max": stored}
            elif key in maxes:
                out[key] = {"score": cell["score"], "max": maxes[key]}
            else:
                out[key] = {"score": cell["score"]}
    return out


def split_series(rows, score_version) -> list:
    """Rows of one rubric only. Missing score_version is v1."""
    want = 2 if score_version in (2, "2", "v2", "V2") else 1
    return [row for row in rows if parse_score_version(row.get("score_version")) == want]


def current_v2(rows) -> dict | None:
    """Head of the v2 series. A v1 row is never returned from here."""
    series = split_series(rows, 2)
    return series[-1] if series else None


def panel_rubric() -> dict:
    return {
        "default_score_version": DEFAULT_SCORE_VERSION,
        "upstream": UPSTREAM,
        "hygiene_note": HYGIENE_NOTE,
        "v1": {"order": list(CATEGORY_ORDER_V1), "max": dict(CATEGORY_MAX_V1)},
        "v2": {
            "order": list(CATEGORY_ORDER_V2),
            "max": dict(CATEGORY_MAX_V2),
            "signals": dict(CATEGORY_SIGNAL_LINES_V2),
        },
    }
