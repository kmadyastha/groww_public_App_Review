"""Write the ≤250-word weekly pulse from locked clusters, quotes, and actions."""

from __future__ import annotations

from collections.abc import Sequence

from pulse.prompts import pulse_title
from pulse.quotes import quote_attribution
from pulse.schemas import (
    ActionIdea,
    DateWindow,
    ProductInfo,
    PulseNote,
    Quote,
    SanitizedReview,
    ThemeCluster,
    ThemeHighlight,
)

MAX_PULSE_WORDS = 250


def word_count(text: str) -> int:
    return len(text.split())


def _theme_summary(cluster: ThemeCluster) -> str:
    stores = []
    if cluster.play_count:
        stores.append(f"{cluster.play_count} Play")
    if cluster.app_store_count:
        stores.append(f"{cluster.app_store_count} App Store")
    mix = ", ".join(stores) if stores else "mixed stores"
    return (
        f"{cluster.count} reviews, avg {cluster.avg_rating:.1f}★, "
        f"{cluster.severity} severity ({mix})"
    )


def _highlights(clusters: Sequence[ThemeCluster]) -> list[ThemeHighlight]:
    return [
        ThemeHighlight(name=cluster.name, summary=_theme_summary(cluster))
        for cluster in list(clusters)[:3]
    ]


def render_pulse_body(
    *,
    product: ProductInfo,
    window: DateWindow,
    clusters: Sequence[ThemeCluster],
    quotes: Sequence[Quote],
    actions: Sequence[ActionIdea],
    weeks: int,
) -> str:
    title = pulse_title(product, window)
    top = list(clusters)[:3]
    theme_lines = "\n".join(
        f"   - {cluster.name} — {_theme_summary(cluster)}" for cluster in top
    )
    quote_lines = "\n".join(
        f"   - “{quote.text}” {quote_attribution(quote)}" for quote in quotes
    )
    action_lines = "\n".join(
        f"   - {idea.title} ({idea.owner_hint}) — {idea.rationale} [{idea.theme}]"
        for idea in actions
    )
    body = (
        f"{title}\n\n"
        f"Play covers the {weeks}-week window; App Store public RSS is recent-only.\n\n"
        f"1. Top 3 themes\n{theme_lines}\n\n"
        f"2. What users said (3 quotes)\n{quote_lines}\n\n"
        f"3. Three action ideas\n{action_lines}\n"
    )
    return body.strip() + "\n"


def write_pulse_note(
    *,
    product: ProductInfo,
    window: DateWindow,
    clusters: Sequence[ThemeCluster],
    quotes: Sequence[Quote],
    actions: Sequence[ActionIdea],
    weeks: int,
    reviews: Sequence[SanitizedReview] | None = None,
    feedback: Sequence[str] | None = None,
) -> PulseNote:
    del reviews
    if len(list(clusters)[:3]) < 3:
        raise ValueError("need 3 clustered themes to write the pulse")
    if len(quotes) != 3 or len(actions) != 3:
        raise ValueError("need 3 quotes and 3 actions")
    body = render_pulse_body(
        product=product,
        window=window,
        clusters=clusters,
        quotes=quotes,
        actions=actions,
        weeks=weeks,
    )
    if word_count(body) > MAX_PULSE_WORDS:
        trimmed = [
            idea.model_copy(
                update={"rationale": " ".join(idea.rationale.split()[:12]).rstrip(".,") + "."}
            )
            for idea in actions
        ]
        body = render_pulse_body(
            product=product,
            window=window,
            clusters=clusters,
            quotes=quotes,
            actions=trimmed,
            weeks=weeks,
        )
        actions = trimmed
    aggressive = bool(feedback and any(item.startswith("length:") for item in feedback))
    if word_count(body) > MAX_PULSE_WORDS or aggressive:
        lines = [
            line
            for line in body.splitlines()
            if "App Store public RSS is recent-only" not in line
        ]
        body = "\n".join(lines).strip() + "\n"
        if word_count(body) > MAX_PULSE_WORDS or aggressive:
            trimmed = [
                idea.model_copy(
                    update={"rationale": " ".join(idea.rationale.split()[:8]).rstrip(".,") + "."}
                )
                for idea in actions
            ]
            body = render_pulse_body(
                product=product,
                window=window,
                clusters=clusters,
                quotes=quotes,
                actions=trimmed,
                weeks=weeks,
            )
            if aggressive:
                lines = [
                    line
                    for line in body.splitlines()
                    if "App Store public RSS is recent-only" not in line
                ]
                body = "\n".join(lines).strip() + "\n"
            actions = trimmed
    return PulseNote(
        title=pulse_title(product, window),
        themes=_highlights(clusters),
        quotes=list(quotes),
        actions=list(actions),
        body=body,
    )
