"""
SoleOracle — Oracle Engine v1
Production estimator + AI cop verdict generator.

Uses heuristic models built from sneaker market knowledge:
  - Brand + silhouette history → estimated production
  - Multi-signal scoring → COP / WAIT / PASS verdict
  - Comparable analysis → ROI projection range
"""
import re, math, logging
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger("soleoracle.oracle")

# ═══════════════════════════════════════════════
# PRODUCTION ESTIMATOR
# Estimates production numbers when no leak exists
# ═══════════════════════════════════════════════

# Historical production baselines by silhouette family
# Source: aggregated from StockX volume data, community leaks, industry estimates
SILHOUETTE_PRODUCTION = {
    # Jordan Retros
    "jordan 1 high": 80_000,
    "jordan 1 low": 150_000,
    "jordan 1 mid": 300_000,
    "jordan 2": 60_000,
    "jordan 3": 70_000,
    "jordan 4": 65_000,
    "jordan 5": 60_000,
    "jordan 6": 55_000,
    "jordan 7": 45_000,
    "jordan 8": 40_000,
    "jordan 9": 35_000,
    "jordan 10": 35_000,
    "jordan 11": 100_000,
    "jordan 12": 60_000,
    "jordan 13": 50_000,
    "jordan 14": 35_000,
    # Nike icons
    "air force 1": 500_000,
    "air max 1": 80_000,
    "air max 90": 120_000,
    "air max 95": 100_000,
    "air max 97": 80_000,
    "dunk low": 120_000,
    "dunk high": 60_000,
    "sb dunk low": 15_000,
    "sb dunk high": 12_000,
    "vapormax": 80_000,
    "air max plus": 90_000,
    "pegasus": 200_000,
    # Nike signature
    "kobe": 25_000,
    "kobe protro": 20_000,
    "lebron": 40_000,
    "kyrie": 50_000,
    "kd": 35_000,
    "ja ": 45_000,
    "tatum": 40_000,
    "foamposite": 20_000,
    # adidas
    "yeezy 350": 50_000,
    "yeezy 500": 30_000,
    "yeezy 700": 25_000,
    "yeezy slide": 100_000,
    "ultraboost": 150_000,
    "samba": 200_000,
    "campus": 120_000,
    "gazelle": 120_000,
    # New Balance
    "new balance 550": 100_000,
    "new balance 2002": 60_000,
    "new balance 990": 30_000,
    "new balance 991": 20_000,
    "new balance 992": 25_000,
    "new balance 993": 30_000,
    "new balance 1906": 50_000,
    # Others
    "gel-kayano": 50_000,
    "gel-lyte": 30_000,
    "converse": 200_000,
}

# Multipliers for special edition signals
EDITION_MULTIPLIERS = {
    # Reduce production (more limited)
    "friends and family": 0.01,
    "f&f": 0.01,
    "sample": 0.02,
    "player exclusive": 0.05,
    "pe ": 0.05,
    "1 of ": 0.005,
    "collab": 0.3,
    "x ": 0.4,   # collab indicator
    "travis scott": 0.15,
    "off-white": 0.15,
    "union": 0.2,
    "a ma maniére": 0.2,
    "fragment": 0.2,
    "sacai": 0.25,
    "concepts": 0.3,
    "patta": 0.3,
    "kith": 0.3,
    "stussy": 0.25,
    "cactus jack": 0.15,
    "eminem": 0.05,
    "trophy room": 0.15,
    "sp ": 0.4,
    "special edition": 0.5,
    "limited edition": 0.35,
    "quickstrike": 0.25,
    "tier 0": 0.2,
    # Increase production (wider release)
    "restock": 2.0,
    "retro": 0.9,
    "reimagined": 0.7,
    "craft": 0.6,
    "se ": 0.7,
    "premium": 0.6,
    "og": 0.85,
    "triple white": 3.0,
    "triple black": 2.5,
    "panda": 4.0,
    "gs": 1.5,  # grade school
    "ps": 1.0,  # preschool
    "td": 1.0,  # toddler
    "wmns": 0.8,
    "women's": 0.8,
}


def estimate_production(name: str, brand: str, retail_price: Optional[float] = None) -> dict:
    """
    Estimate production number for a sneaker based on its name, brand, and price.
    Returns: {production_estimate, confidence, reasoning}
    """
    nl = name.lower()
    reasons = []

    # Step 1: Find base production from silhouette match
    base = None
    matched_sil = None
    for sil, prod in SILHOUETTE_PRODUCTION.items():
        if sil in nl:
            if matched_sil is None or len(sil) > len(matched_sil):
                base = prod
                matched_sil = sil

    if base is None:
        # Fallback by brand
        brand_defaults = {
            "Jordan": 65_000, "Nike": 100_000, "adidas": 80_000,
            "New Balance": 50_000, "ASICS": 40_000, "Puma": 60_000,
            "Converse": 100_000, "Reebok": 60_000, "Saucony": 30_000,
            "HOKA": 50_000,
        }
        base = brand_defaults.get(brand, 75_000)
        reasons.append(f"Brand default for {brand}: ~{base:,} pairs")
    else:
        reasons.append(f"Base silhouette ({matched_sil}): ~{base:,} pairs")

    # Step 2: Apply edition multipliers
    cumulative_mult = 1.0
    applied_mults = []
    for keyword, mult in EDITION_MULTIPLIERS.items():
        if keyword in nl:
            cumulative_mult *= mult
            direction = "↓" if mult < 1.0 else "↑"
            applied_mults.append(f"{keyword.strip()} ({direction}{mult:.1f}x)")

    if applied_mults:
        reasons.append("Edition signals: " + ", ".join(applied_mults[:4]))

    # Cap the cumulative multiplier
    cumulative_mult = max(0.005, min(5.0, cumulative_mult))

    # Step 3: Price-based adjustment
    if retail_price:
        if retail_price >= 300:
            cumulative_mult *= 0.6
            reasons.append(f"Premium price ${retail_price:.0f} → lower volume")
        elif retail_price >= 250:
            cumulative_mult *= 0.75
        elif retail_price <= 100:
            cumulative_mult *= 1.3
            reasons.append(f"Accessible price ${retail_price:.0f} → higher volume")

    estimate = int(base * cumulative_mult)

    # Step 4: Sanity bounds
    estimate = max(200, min(2_000_000, estimate))

    # Round to reasonable precision
    if estimate >= 100_000:
        estimate = round(estimate, -4)  # nearest 10K
    elif estimate >= 10_000:
        estimate = round(estimate, -3)  # nearest 1K
    elif estimate >= 1_000:
        estimate = round(estimate, -2)  # nearest 100
    else:
        estimate = round(estimate, -1)  # nearest 10

    # Confidence based on how many signals we used
    signal_count = (1 if matched_sil else 0) + len(applied_mults) + (1 if retail_price else 0)
    if signal_count >= 3:
        confidence = "Estimated"
    elif signal_count >= 1:
        confidence = "Estimated"
    else:
        confidence = "Rough Estimate"

    return {
        "production_estimate": estimate,
        "confidence": confidence,
        "reasoning": reasons,
    }


# ═══════════════════════════════════════════════
# COMPARABLE ANALYSIS ENGINE
# Uses historical patterns to project ROI
# ═══════════════════════════════════════════════

# Historical resale multiples by production tier + brand
# Format: (production_range_low, production_range_high): {brand: avg_resale_multiple}
HISTORICAL_MULTIPLES = {
    (0, 1_000): {"Jordan": 8.0, "Nike": 6.0, "adidas": 5.0, "_default": 4.0},
    (1_000, 5_000): {"Jordan": 4.5, "Nike": 3.5, "adidas": 3.0, "_default": 2.5},
    (5_000, 15_000): {"Jordan": 2.8, "Nike": 2.2, "adidas": 2.0, "_default": 1.8},
    (15_000, 30_000): {"Jordan": 2.0, "Nike": 1.7, "adidas": 1.5, "_default": 1.4},
    (30_000, 60_000): {"Jordan": 1.5, "Nike": 1.3, "adidas": 1.2, "_default": 1.1},
    (60_000, 100_000): {"Jordan": 1.2, "Nike": 1.1, "adidas": 1.05, "_default": 1.0},
    (100_000, 300_000): {"Jordan": 1.0, "Nike": 0.95, "adidas": 0.9, "_default": 0.9},
    (300_000, 10_000_000): {"Jordan": 0.85, "Nike": 0.85, "adidas": 0.85, "_default": 0.85},
}

# Hype silhouette bonus — these command premiums above their production tier
SILHOUETTE_HYPE_BONUS = {
    "jordan 1 high": 1.4,
    "jordan 4": 1.5,
    "jordan 11": 1.3,
    "jordan 3": 1.25,
    "sb dunk low": 1.6,
    "kobe": 1.8,
    "kobe protro": 1.7,
    "foamposite": 1.3,
    "yeezy 350": 1.2,
    "air max 1": 1.15,
    "new balance 990": 1.3,
    "off-white": 2.0,
    "travis scott": 2.5,
}


def _get_historical_multiple(production: int, brand: str) -> float:
    for (lo, hi), multiples in HISTORICAL_MULTIPLES.items():
        if lo <= production < hi:
            return multiples.get(brand, multiples["_default"])
    return 1.0


def _get_hype_bonus(name: str) -> float:
    nl = name.lower()
    bonus = 1.0
    for keyword, mult in SILHOUETTE_HYPE_BONUS.items():
        if keyword in nl:
            bonus = max(bonus, mult)
    return bonus


# ═══════════════════════════════════════════════
# VERDICT ENGINE
# ═══════════════════════════════════════════════

def generate_verdict(
    name: str,
    brand: str,
    retail_price: Optional[float],
    release_date: Optional[datetime],
    production_number: Optional[int],
    production_confidence: str = "Estimated",
    heat_index: float = 5.0,
    hype_score: float = 5.0,
    scarcity_score: float = 5.0,
    resale_multiple: float = 1.0,
    velocity_score: float = 5.0,
    stockx_price: Optional[float] = None,
    goat_price: Optional[float] = None,
) -> dict:
    """
    Generate a COP / WAIT / PASS verdict with reasoning.
    This is the core Oracle engine.
    """
    nl = name.lower()
    reasons = []
    score = 0.0  # -100 to +100 scale

    # ── Step 1: Ensure we have a production estimate ──
    if production_number is None or production_number == 0:
        est = estimate_production(name, brand, retail_price)
        production_number = est["production_estimate"]
        production_confidence = est["confidence"]

    # ── Step 2: Scarcity signal (max ±30 pts) ──
    if production_number <= 3_000:
        score += 30
        reasons.append(f"Ultra-scarce: ~{production_number:,} pairs → extremely high resale potential")
    elif production_number <= 10_000:
        score += 22
        reasons.append(f"Very limited: ~{production_number:,} pairs → strong scarcity premium expected")
    elif production_number <= 25_000:
        score += 15
        reasons.append(f"Limited run: ~{production_number:,} pairs → moderate scarcity advantage")
    elif production_number <= 60_000:
        score += 5
        reasons.append(f"Mid-range production: ~{production_number:,} pairs → typical release volume")
    elif production_number <= 150_000:
        score -= 5
        reasons.append(f"Wide release: ~{production_number:,} pairs → low scarcity premium")
    else:
        score -= 15
        reasons.append(f"Mass release: ~{production_number:,} pairs → likely bricks or sits below retail")

    # ── Step 3: Brand + silhouette signal (max ±20 pts) ──
    hype_bonus = _get_hype_bonus(name)
    if hype_bonus >= 2.0:
        score += 20
        reasons.append("Elite-tier collaboration/silhouette → collector frenzy expected")
    elif hype_bonus >= 1.5:
        score += 15
        reasons.append("High-demand silhouette → historically strong resale performance")
    elif hype_bonus >= 1.2:
        score += 8
        reasons.append("Popular silhouette with consistent demand")
    elif brand in ("Jordan", "Nike"):
        score += 3
    else:
        score -= 2

    # ── Step 4: Resale multiple signal (max ±25 pts) ──
    actual_multiple = resale_multiple
    if stockx_price and retail_price and retail_price > 0:
        actual_multiple = stockx_price / retail_price
    elif goat_price and retail_price and retail_price > 0:
        actual_multiple = goat_price / retail_price

    if actual_multiple > 1.0 and stockx_price:
        # We have real resale data
        if actual_multiple >= 3.0:
            score += 25
            reasons.append(f"Resale at {actual_multiple:.1f}x retail → confirmed profit machine")
        elif actual_multiple >= 2.0:
            score += 18
            reasons.append(f"Resale at {actual_multiple:.1f}x retail → strong flip potential")
        elif actual_multiple >= 1.5:
            score += 12
            reasons.append(f"Resale at {actual_multiple:.1f}x retail → decent margin after fees")
        elif actual_multiple >= 1.1:
            score += 4
            reasons.append(f"Resale at {actual_multiple:.1f}x retail → thin margins, risky flip")
        elif actual_multiple < 0.9:
            score -= 15
            reasons.append(f"Resale at {actual_multiple:.1f}x retail → trading below retail")
    else:
        # Project from comparable historical data
        projected_mult = _get_historical_multiple(production_number, brand) * hype_bonus
        if projected_mult >= 2.5:
            score += 18
            reasons.append(f"Comparable shoes averaged {projected_mult:.1f}x resale historically")
        elif projected_mult >= 1.8:
            score += 12
        elif projected_mult >= 1.3:
            score += 5
        elif projected_mult < 1.0:
            score -= 10
            reasons.append(f"Similar releases averaged below retail ({projected_mult:.1f}x)")
        actual_multiple = projected_mult

    # ── Step 5: Heat index integration (max ±15 pts) ──
    if heat_index >= 8.5:
        score += 15
        reasons.append(f"Heat Index {heat_index}/10 → top-tier community buzz")
    elif heat_index >= 7.0:
        score += 8
    elif heat_index >= 5.0:
        score += 2
    elif heat_index < 3.0:
        score -= 10
        reasons.append(f"Heat Index {heat_index}/10 → low community interest")

    # ── Step 6: Timing signal (max ±10 pts) ──
    if release_date:
        days_out = (release_date - datetime.utcnow()).days
        if days_out < 0:
            # Already dropped — check if it's still profitable
            if actual_multiple >= 1.5:
                score += 5
                reasons.append("Already released but still trading above retail")
            else:
                score -= 5
        elif days_out <= 7:
            score += 5
            reasons.append(f"Dropping in {days_out} days — act now")
        elif days_out <= 30:
            score += 2
        elif days_out > 90:
            score -= 3
            reasons.append(f"Release is {days_out} days away — prices may shift, revisit closer to drop")

    # ── Step 7: Price accessibility (max ±5 pts) ──
    if retail_price:
        if retail_price <= 130:
            score += 3
            reasons.append(f"Low entry point at ${retail_price:.0f} → lower risk per pair")
        elif retail_price >= 300:
            score -= 3
            reasons.append(f"High retail at ${retail_price:.0f} → larger capital at risk")

    # ── Compute final verdict ──
    score = max(-100, min(100, score))

    if score >= 40:
        verdict = "COP"
        confidence = min(98, 60 + int(score * 0.4))
    elif score >= 15:
        verdict = "COP"
        confidence = min(80, 50 + int(score * 0.5))
    elif score >= -5:
        verdict = "WAIT"
        confidence = 40 + abs(int(score))
    elif score >= -25:
        verdict = "PASS"
        confidence = min(80, 50 + abs(int(score)))
    else:
        verdict = "PASS"
        confidence = min(95, 60 + abs(int(score * 0.4)))

    # ── ROI projection ──
    if retail_price and retail_price > 0:
        base_mult = actual_multiple if actual_multiple > 0 else _get_historical_multiple(production_number, brand) * hype_bonus
        # Apply uncertainty spread
        spread = 0.3 if production_confidence == "Confirmed" else (0.4 if production_confidence == "Rumored" else 0.5)
        low_mult = max(0.5, base_mult * (1 - spread))
        high_mult = base_mult * (1 + spread * 0.6)

        projected_low = int(retail_price * low_mult)
        projected_high = int(retail_price * high_mult)
        roi_low = round((low_mult - 1) * 100, 0)
        roi_high = round((high_mult - 1) * 100, 0)

        # Risk tier
        if low_mult >= 1.3:
            risk = "Low"
        elif low_mult >= 1.0:
            risk = "Medium"
        elif low_mult >= 0.8:
            risk = "High"
        else:
            risk = "Very High"
    else:
        projected_low = None
        projected_high = None
        roi_low = None
        roi_high = None
        risk = "Unknown"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "score": round(score, 1),
        "risk_tier": risk,
        "projected_resale_low": projected_low,
        "projected_resale_high": projected_high,
        "roi_low": roi_low,
        "roi_high": roi_high,
        "production_estimate": production_number,
        "production_confidence": production_confidence,
        "reasoning": reasons[:5],  # Top 5 reasons
        "signals": {
            "scarcity": round(scarcity_score, 1),
            "hype": round(hype_score, 1),
            "resale_multiple": round(actual_multiple, 2),
            "velocity": round(velocity_score, 1),
            "heat_index": round(heat_index, 1),
        },
    }


def generate_verdict_from_drop(drop) -> dict:
    """Convenience wrapper — pass a SneakerDrop ORM object."""
    return generate_verdict(
        name=drop.name,
        brand=drop.brand,
        retail_price=drop.retail_price,
        release_date=drop.release_date,
        production_number=drop.production_number,
        production_confidence=drop.production_confidence or "Estimated",
        heat_index=drop.heat_index or 5.0,
        hype_score=drop.hype_score or 5.0,
        scarcity_score=drop.scarcity_score or 5.0,
        resale_multiple=drop.resale_multiple or 1.0,
        velocity_score=drop.velocity_score or 5.0,
        stockx_price=drop.stockx_price,
        goat_price=drop.goat_price,
    )
