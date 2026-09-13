"""Phase 1 public-export ingest (eval E1-01 … E1-09)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from pulse.config import load_config
from pulse.ingest import IngestError, date_window, load_reviews, write_reviews
from pulse.ingest.app_store import load_app_store_reviews
from pulse.ingest.common import load_tabular_records, parse_records, to_ist_date
from pulse.ingest.play_store import load_play_reviews
from pulse.schemas import DateWindow, RawReview

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW = DateWindow(start_date=date(2026, 6, 27), end_date=date(2026, 9, 5))
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return load_config()


def _parse_file(path: Path, config, *, default_store=None) -> list[RawReview]:
    records = load_tabular_records(path)
    return parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
        default_store=default_store,
    )


def test_sample_fixture_has_required_fields(config):
    reviews = _parse_file(FIXTURES / "reviews_sample.json", config)
    assert len(reviews) == 5
    stores = {row.store for row in reviews}
    assert stores == {"play", "app_store"}
    for row in reviews:
        assert 1 <= row.rating <= 5
        assert row.text or row.title
        assert isinstance(row.date, date)
        assert row.store in {"play", "app_store"}
        assert "author" not in row.model_dump()
        assert "username" not in RawReview.model_fields


def test_stale_export_fails_closed(config, tmp_path):
    parsed = _parse_file(FIXTURES / "reviews_stale.json", config)
    assert parsed == []
    with pytest.raises(IngestError, match="date window|stale|no reviews"):
        load_reviews(
            WINDOW,
            config=config,
            play_path=FIXTURES / "reviews_stale.json",
            raw_dir=tmp_path,
        )


def test_empty_and_whitespace_bodies_dropped(config):
    records = load_tabular_records(FIXTURES / "play_filter_rows.csv")
    reviews = _parse_file(FIXTURES / "play_filter_rows.csv", config, default_store="play")
    assert len(records) > len(reviews)
    texts = [row.text for row in reviews]
    assert any("two full days" in text for text in texts)
    assert any("KYC got stuck" in text and "<" not in text for text in texts)
    assert all("वेरिफिकेशन" not in text for text in texts)
    assert all("bakwas" not in text.lower() for text in texts)
    assert all("🔥" not in text for text in texts)
    assert all(len(re.findall(r"[A-Za-z]+", text)) >= 8 for text in texts)


def test_identity_columns_not_mapped_from_csv(config):
    reviews = load_play_reviews(
        FIXTURES / "play_with_identity.csv",
        window=WINDOW,
        config=config,
    )
    assert len(reviews) == 1
    dumped = reviews[0].model_dump()
    assert "author" not in dumped
    assert "email" not in dumped
    assert "device" not in dumped
    assert reviews[0].text == "Need help with verification for my KYC details today."
    with pytest.raises(Exception):
        RawReview.model_validate({**dumped, "author": "alice"})


def test_window_boundaries_are_inclusive(config):
    reviews = _parse_file(FIXTURES / "reviews_boundary.json", config, default_store="play")
    ids = {row.review_id_source for row in reviews}
    assert "bound-start" in ids
    assert "bound-end" in ids
    assert "bound-ist" in ids
    assert to_ist_date("2026-06-26T20:00:00Z") == date(2026, 6, 27)


def test_non_groww_package_rows_dropped(config):
    reviews = load_play_reviews(
        FIXTURES / "play_mixed_package.csv",
        window=WINDOW,
        config=config,
    )
    assert len(reviews) == 1
    assert "Groww" in reviews[0].text or "verification" in reviews[0].text.lower()


def test_invalid_ratings_dropped(config):
    reviews = load_play_reviews(
        FIXTURES / "play_filter_rows.csv",
        window=WINDOW,
        config=config,
    )
    assert all(1 <= row.rating <= 5 for row in reviews)
    assert not any("Zero stars" in row.text or "Six stars" in row.text or "Word rating" in row.text for row in reviews)


def test_play_and_app_store_merge_tags_store(config, tmp_path):
    reviews = load_reviews(
        WINDOW,
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        raw_dir=tmp_path,
    )
    assert {row.store for row in reviews} == {"play", "app_store"}


def test_header_only_and_empty_file_fail_closed(config, tmp_path):
    with pytest.raises(IngestError, match="header-only|empty"):
        load_reviews(
            WINDOW,
            config=config,
            play_path=FIXTURES / "play_header_only.csv",
            raw_dir=tmp_path,
        )
    with pytest.raises(IngestError, match="empty file"):
        load_reviews(
            WINDOW,
            config=config,
            play_path=FIXTURES / "play_empty.csv",
            raw_dir=tmp_path,
        )


def test_unknown_json_schema_fails_closed(config, tmp_path):
    with pytest.raises(IngestError, match="unknown JSON schema"):
        load_reviews(
            WINDOW,
            config=config,
            play_path=FIXTURES / "unknown_schema.json",
            raw_dir=tmp_path,
        )


def test_app_store_rss_json_skips_author_and_app_entry(config):
    reviews = load_app_store_reviews(
        FIXTURES / "app_store_rss.json",
        window=WINDOW,
        config=config,
    )
    assert len(reviews) == 1
    assert reviews[0].store == "app_store"
    assert reviews[0].review_id_source == "ios-rss-1"
    assert "The e-KYC camera step failed twice during account setup." in reviews[0].text
    assert "ios.user" not in reviews[0].text
    assert "author" not in reviews[0].model_dump()


def test_same_text_on_both_stores_is_kept_twice(config):
    records = [
        {
            "store": "play",
            "review_id_source": "p1",
            "rating": 2,
            "text": "KYC verification is slow and users wait for two days.",
            "date": "2026-08-01",
            "package": "com.nextbillion.groww",
            "locale": "en_IN",
        },
        {
            "store": "app_store",
            "review_id_source": "i1",
            "rating": 2,
            "text": "KYC verification is slow and users wait for two days.",
            "date": "2026-08-01",
            "locale": "en_IN",
        },
    ]
    reviews = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
    )
    assert len(reviews) == 2
    assert {row.store for row in reviews} == {"play", "app_store"}


def test_duplicate_source_id_keeps_latest(config):
    records = [
        {
            "store": "play",
            "review_id_source": "dup",
            "rating": 2,
            "text": "This is the older copy of the same review text.",
            "date": "2026-07-01",
            "package": "com.nextbillion.groww",
            "locale": "en_IN",
        },
        {
            "store": "play",
            "review_id_source": "dup",
            "rating": 1,
            "text": "This is the newer copy of the same review text.",
            "date": "2026-08-01",
            "package": "com.nextbillion.groww",
            "locale": "en_IN",
        },
    ]
    reviews = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
        default_store="play",
    )
    assert len(reviews) == 1
    assert reviews[0].text.startswith("Newer")


def test_utf8_bom_csv(config, tmp_path):
    path = tmp_path / "bom.csv"
    body = "rating,title,text,date,package,locale\n2,BOM,KYC has been pending for two full days now.,2026-08-01,com.nextbillion.groww,en_IN\n"
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    reviews = load_play_reviews(path, window=WINDOW, config=config)
    assert len(reviews) == 1
    assert reviews[0].text == "KYC has been pending for two full days now."


def test_no_sources_fails_closed(config, tmp_path):
    with pytest.raises(IngestError, match="no public reviews found"):
        load_reviews(WINDOW, config=config, raw_dir=tmp_path, fetch_rss=False, fetch_public=False)


def test_play_only_when_app_store_missing(config, tmp_path):
    play = tmp_path / "play_reviews.json"
    play.write_text(
        json.dumps(
            [
                {
                    "rating": 2,
                    "title": "KYC",
                    "text": "KYC verification is still pending after two full days.",
                    "date": "2026-08-01",
                    "package": "com.nextbillion.groww",
                    "locale": "en_IN",
                }
            ]
        ),
        encoding="utf-8",
    )
    reviews = load_reviews(WINDOW, config=config, raw_dir=tmp_path, fetch_rss=False)
    assert len(reviews) == 1
    assert reviews[0].store == "play"


def test_write_reviews_and_cli(config, tmp_path):
    dest = tmp_path / "out"
    reviews = load_reviews(
        WINDOW,
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        raw_dir=tmp_path,
    )
    out = write_reviews(reviews, dest)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload) == 5
    assert all("author" not in row for row in payload)

    from pulse.cli import main

    code = main(
        [
            "ingest",
            "--play",
            str(FIXTURES / "reviews_sample.json"),
            "--raw-dir",
            str(tmp_path),
            "--out",
            str(dest / "cli"),
            "--no-fetch",
            "--weeks",
            "10",
            "--end-date",
            "2026-09-05",
        ]
    )
    assert code == 0
    assert (dest / "cli" / "ingested.json").is_file()


def test_date_window_matches_ten_weeks():
    window = date_window(10, end=date(2026, 9, 5))
    assert window.start_date == date(2026, 6, 27)
    assert window.end_date == date(2026, 9, 5)


def test_operator_docs_explain_public_fetch():
    readme = (REPO_ROOT / "data" / "raw" / "README.md").read_text(encoding="utf-8")
    assert "python -m pulse ingest" in readme
    assert "google-play-scraper" in readme or "public" in readme.lower()
    assert "login" in readme.lower() or "credential" in readme.lower()


def test_play_scraper_item_drops_username():
    from datetime import datetime

    from pulse.ingest.play_store import scraper_item_to_record

    rec = scraper_item_to_record(
        {
            "reviewId": "abc",
            "userName": "alice",
            "userImage": "http://example.com/x.png",
            "content": "KYC delayed two days.",
            "score": 2,
            "at": datetime(2026, 8, 1, 12, 0, 0),
        },
        play_id="com.nextbillion.groww",
        locale="en_IN",
    )
    assert "userName" not in rec
    assert "userImage" not in rec
    assert rec["text"] == "KYC delayed two days."
    assert rec["rating"] == 2
    assert rec["date"] == "2026-08-01"


def test_short_reviews_are_dropped(config):
    from pulse.ingest.common import is_english_text, review_word_count

    assert review_word_count("good app") < 8
    records = [
        {
            "store": "play",
            "review_id_source": "short",
            "rating": 5,
            "text": "Good app nice",
            "date": "2026-08-01",
            "package": "com.nextbillion.groww",
            "locale": "en_IN",
        }
    ]
    reviews = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
    )
    assert reviews == []


def test_non_english_reviews_are_dropped(config):
    from pulse.ingest.common import is_english_text

    assert not is_english_text("वेरिफिकेशन अटका है दो दिन से")
    assert not is_english_text("Ye app bahut bakwas hai account opening nahi ho raha")
    assert not is_english_text(
        "horrible ui filled with all sorts of nonsense ghatiya update hai please fix scalper"
    )
    assert not is_english_text("oi data add krdo dhan app ki tarah please")
    assert is_english_text("The KYC verification has been pending for two full days now.")
    records = [
        {
            "store": "play",
            "review_id_source": "hi-1",
            "rating": 1,
            "text": "5 din se jyada ho gye account opening process kiye huye",
            "date": "2026-08-01",
            "package": "com.nextbillion.groww",
            "locale": "en_IN",
        }
    ]
    reviews = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
    )
    assert reviews == []

