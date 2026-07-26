import asyncio
from types import SimpleNamespace

import feedparser


def test_twitter_xclid_patch_accepts_proxy_and_future_kwargs():
    # Importing the collector installs the compatibility shim.
    import collectors.twitter_collector  # noqa: F401
    from twscrape import queue_client

    generator = asyncio.run(
        queue_client.XClIdGenStore.get(
            "test-account",
            fresh=True,
            proxy=False,
            future_transport_option="ignored",
        )
    )

    transaction_id = generator.calc(
        "GET",
        "/i/api/graphql/test",
        future_calc_option="ignored",
    )
    assert isinstance(transaction_id, str)
    assert transaction_id


def test_twitter_stops_after_first_shared_queue_timeout(monkeypatch):
    import collectors.twitter_collector as twitter

    attempted_accounts = []

    class FakeAPI:
        async def user_tweets(self, user_id, limit):
            attempted_accounts.append(user_id)
            await asyncio.sleep(1)
            if False:
                yield None

    async def fake_get_api():
        return FakeAPI()

    monkeypatch.setattr(twitter, "_get_api", fake_get_api)
    monkeypatch.setattr(twitter, "get_cached_user_id", lambda username: username)
    monkeypatch.setattr(twitter, "TWITTER_ACCOUNT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(twitter, "TWITTER_RUN_BUDGET_SECONDS", 1.0)

    result = asyncio.run(
        twitter.collect_twitter_accounts(["101", "202", "303"], source_id=18)
    )

    assert result == 0
    assert attempted_accounts == [101]


def test_youtube_ip_block_is_remembered_for_the_run(monkeypatch):
    import collectors.youtube_collector as youtube
    from youtube_transcript_api._errors import RequestBlocked

    calls = []

    class FakeTranscriptAPI:
        def fetch(self, video_id):
            calls.append(video_id)
            raise RequestBlocked(video_id)

    monkeypatch.setattr(youtube, "_transcript_api", FakeTranscriptAPI())
    monkeypatch.setattr(youtube, "_transcript_access_blocked", False)

    assert youtube.fetch_transcript("first") is None
    assert youtube.fetch_transcript("second") is None
    assert calls == ["first"]


def test_youtube_cloud_block_falls_back_to_rss_metadata(monkeypatch):
    import collectors.youtube_collector as youtube

    entry = feedparser.FeedParserDict(
        {
            "yt_videoid": "abc123",
            "link": "https://www.youtube.com/watch?v=abc123",
            "title": "A new memory-system design",
            "media_description": (
                "A technical discussion of cache coherence, memory ordering, "
                "and the measurements used to distinguish their bottlenecks."
            ),
        }
    )
    fake_feed = SimpleNamespace(
        feed=feedparser.FeedParserDict({"title": "Architecture Channel"}),
        entries=[entry],
    )
    inserted = []

    monkeypatch.setattr(youtube.feedparser, "parse", lambda url: fake_feed)
    monkeypatch.setattr(youtube, "_video_exists", lambda url: False)
    monkeypatch.setattr(youtube, "fetch_transcript", lambda video_id: None)
    monkeypatch.setattr(youtube, "_transcript_access_blocked", True)
    monkeypatch.setattr(
        youtube,
        "insert_raw_item",
        lambda **kwargs: inserted.append(kwargs) or 42,
    )

    count = youtube._collect_channel(
        "channel-id",
        "ArchitectureChannel",
        source_id=24,
        cutoff=youtube.datetime(2020, 1, 1, tzinfo=youtube.timezone.utc),
    )

    assert count == 1
    assert len(inserted) == 1
    assert youtube.METADATA_ONLY_MARKER in inserted[0]["raw_text"]
    assert "cache coherence" in inserted[0]["raw_text"]


def test_quick_processing_stops_at_card_cap(monkeypatch):
    import processing.card_generator as generator

    items = [
        {
            "id": item_id,
            "title": f"AMD architecture update {item_id}",
            "url": f"https://example{item_id}.com/story",
            "raw_text": "Technical source text",
            "source_type": "rss",
            "credibility": 8,
        }
        for item_id in range(1, 5)
    ]
    generated_for = []

    monkeypatch.setattr(generator, "get_unprocessed_items", lambda limit: items)
    monkeypatch.setattr(generator, "get_recent_titles", lambda: [])
    monkeypatch.setattr(generator, "_get_recent_domains", lambda: set())
    monkeypatch.setattr(generator, "is_duplicate", lambda title, recent: False)
    monkeypatch.setattr(
        generator,
        "generate_intelligence_card",
        lambda raw_item_id, **kwargs: (
            generated_for.append(raw_item_id)
            or {
                "one_line_summary": f"Card {raw_item_id}",
                "importance_score": 0.8,
            }
        ),
    )
    monkeypatch.setattr(generator, "insert_intelligence_card", lambda *args: None)
    monkeypatch.setattr(generator, "log_api_usage", lambda *args: None)

    count = generator.process_unprocessed_items(max_items=50, max_cards=2)

    assert count == 2
    assert generated_for == [1, 2]
