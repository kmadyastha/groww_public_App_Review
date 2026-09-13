# Public review downloads (`data/raw/`)

Ingest **downloads public reviews automatically**. No Play Console login and no manual CSV export.

```text
python -m pulse ingest --weeks 8 --out data/raw
```

That calls:

- **Google Play** — `google-play-scraper` (public listing, `hl=en` `gl=in`), no credentials. Fallback: the same public `batchexecute` RPC the Play web UI uses.
- **App Store** — official iTunes customer-reviews RSS for id `1404871703` (pages 1–10, Apple’s public cap ~500).

Files written here (gitignored except this README):

| File | Source |
| --- | --- |
| `play_reviews.json` | Public Play listing, last 8–12 weeks, **no usernames**, **English**, **≥ 8 words** |
| `app_store_reviews.json` | Public App Store RSS, same quality filters |

Quality filters (applied on ingest and on these files): drop review text shorter than 8 words; drop non-English text (other scripts and Hindi/Hinglish).

| `ingested.json` | Merged, window-filtered rows |

Re-download even if files exist:

```text
python -m pulse ingest --refresh --weeks 8
```

Offline / fixtures only: `--no-fetch`.

Play Console and logged-in scraping are not used.
