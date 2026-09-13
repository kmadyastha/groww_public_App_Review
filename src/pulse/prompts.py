"""Prompt templates and closed theme seeds for Groq intelligence nodes."""

from __future__ import annotations

from pulse.schemas import DateWindow, ProductInfo, SanitizedReview

SEED_THEMES = (
    "Charts and trading tools",
    "Brokerage and charges",
    "Order execution and fills",
    "Support and account access",
    "App stability and updates",
)

FOLD_IN_THEMES = (
    "Payments and UPI",
    "Withdrawals",
    "IPO applications",
    "Loan-app cross-sell",
    "Alerts",
)

FORBIDDEN_EMPTY_SEEDS = ("onboarding", "statements", "statement / reports")

CANDIDATE_THEMES = SEED_THEMES + FOLD_IN_THEMES + ("Ease of use",)

SYSTEM_ANALYST = (
    "You analyze public Groww app-store reviews for Product, Support, and Growth. "
    "Use only the candidate theme names provided. Do not invent quotes. "
    "Do not use reviewer names, emails, or store source ids. "
    "Do not force Onboarding or Statements themes unless reviews clearly match. "
    "KYC, ReKYC, camera verification, and frozen accounts belong in "
    "Support and account access. You are called via Groq, not OpenAI."
)

BANNED_ACTION_SLOGANS = (
    "improve ux",
    "listen to users",
    "fix bugs",
    "do better",
    "make it better",
    "enhance experience",
)


def review_line(review: SanitizedReview, *, max_text_words: int = 40) -> str:
    title = f" title={review.title}" if review.title else ""
    words = review.text.split()
    text = " ".join(words[:max_text_words]) if len(words) > max_text_words else review.text
    return (
        f"- id={review.review_id} store={review.store} rating={review.rating} "
        f"date={review.date.isoformat()}{title} text={text}"
    )


def cluster_chunk_prompt(
    reviews: list[SanitizedReview],
    *,
    candidates: tuple[str, ...] = CANDIDATE_THEMES,
) -> str:
    lines = "\n".join(review_line(row) for row in reviews)
    names = "; ".join(candidates)
    return (
        f"{SYSTEM_ANALYST}\n\n"
        f"Assign each review to exactly one theme from: {names}.\n"
        "Return JSON {\"assignments\": [{\"review_id\": \"...\", \"theme\": \"...\"}, ...]}.\n"
        "Use the opaque id values given. Do not echo source ids.\n\n"
        f"Reviews:\n{lines}"
    )


def quote_nominate_prompt(
    reviews: list[SanitizedReview],
    theme_names: list[str],
) -> str:
    lines = "\n".join(review_line(row) for row in reviews)
    return (
        f"{SYSTEM_ANALYST}\n\n"
        f"Themes: {', '.join(theme_names)}.\n"
        "Nominate exactly 3 distinct review_id values for verbatim quotes. "
        "Prefer distinct themes, mix stores when possible, and prefer 1–3★ over 5★ UI praise.\n"
        "Return JSON {\"review_ids\": [\"id1\", \"id2\", \"id3\"]}.\n\n"
        f"Reviews:\n{lines}"
    )


def pulse_title(product: ProductInfo, window: DateWindow) -> str:
    return (
        f"{product.name} Weekly Review Pulse — "
        f"{window.start_date.isoformat()} to {window.end_date.isoformat()}"
    )
