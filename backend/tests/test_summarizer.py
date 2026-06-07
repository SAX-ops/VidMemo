from services.summarizer import (
    _is_bilibili_url,
    _parse_vtt,
    _pick_best_subtitle,
    _time_to_seconds,
)


def test_is_bilibili_url_matches_domains():
    assert _is_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD")
    assert _is_bilibili_url("https://bilibili.com/video/BV1xx411c7mD")
    assert _is_bilibili_url("https://b23.tv/abc123")
    assert _is_bilibili_url("https://www.bilibili.com/bangumi/play/ep123")


def test_is_bilibili_url_rejects_others():
    assert not _is_bilibili_url("https://www.youtube.com/watch?v=xxx")
    assert not _is_bilibili_url("https://www.douyin.com/video/123")
    assert not _is_bilibili_url("https://example.com")


def test_time_to_seconds():
    assert _time_to_seconds("00:00:00.000") == 0.0
    assert _time_to_seconds("00:01:30.500") == 90.5
    assert _time_to_seconds("01:02:03.456") == 3723.456


def test_parse_vtt_simple(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Hello world\n\n"
        "00:00:04.000 --> 00:00:06.500\n"
        "Second line\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert len(segs) == 2
    assert segs[0]["start"] == 1.0
    assert segs[0]["end"] == 3.0
    assert segs[0]["text"] == "Hello world"
    assert segs[1]["start"] == 4.0
    assert segs[1]["end"] == 6.5


def test_parse_vtt_strips_html_tags(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "<c.color>Colored</c> text\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert segs[0]["text"] == "Colored text"


def test_parse_vtt_dedup_consecutive(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Same text\n\n"
        "00:00:02.500 --> 00:00:03.500\n"
        "Same text\n\n"
        "00:00:04.000 --> 00:00:05.000\n"
        "Different\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert len(segs) == 2
    assert segs[0]["text"] == "Same text"
    assert segs[1]["text"] == "Different"


def test_pick_prefers_manual_zh_hans():
    manual = {
        "en": [{"ext": "vtt", "url": "u-en"}],
        "zh-Hans": [{"ext": "vtt", "url": "u-zh"}],
    }
    auto = {}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "zh-Hans"
    assert url == "u-zh"
    assert kind == "manual"
    assert is_target is True


def test_pick_falls_back_to_other_lang_with_flag():
    manual = {"en": [{"ext": "vtt", "url": "u-en"}]}
    auto = {}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "en"
    assert url == "u-en"
    assert kind == "manual"
    assert is_target is False


def test_pick_falls_back_to_auto_when_no_manual():
    manual = {}
    auto = {"zh-Hans": [{"ext": "vtt", "url": "u-zh-auto"}]}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "zh-Hans"
    assert kind == "auto"
    assert is_target is True


def test_pick_returns_empty_when_no_subtitles():
    lang, url, kind, is_target = _pick_best_subtitle({}, {}, "zh")
    assert lang == ""
    assert url is None
    assert is_target is False
