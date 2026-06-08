import json
import os
from unittest.mock import MagicMock

import pytest

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


@pytest.mark.network
def test_extract_bilibili_real_video():
    """Hit the real B站 API. Skip when offline."""
    from services.summarizer import _extract_bilibili

    result = _extract_bilibili("https://www.bilibili.com/video/BV1GJ411x7h7")
    assert result["has_subtitle"] is True
    assert result["language"] in ("zh-Hans", "zh", "ai-zh")
    assert result["subtitle_type"] in ("manual", "auto")
    assert len(result["segments"]) > 0
    assert result["segments"][0]["start"] >= 0
    assert result["segments"][0]["text"]  # non-empty


def test_extract_returns_bilibili_result(monkeypatch):
    """When B站 extractor returns a result, use it directly without calling yt-dlp."""
    from services.summarizer import SubtitleExtractor

    bilibili_result = {
        "has_subtitle": True, "language": "zh-Hans", "subtitle_type": "manual",
        "is_target_language": True, "fallback_mode": None,
        "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}],
        "full_text": "你好",
    }
    monkeypatch.setattr("services.summarizer._extract_bilibili", lambda url: bilibili_result)
    mock_info = MagicMock()
    monkeypatch.setattr("services.summarizer._get_video_info", mock_info)

    result = SubtitleExtractor().extract("https://www.bilibili.com/video/BV1xx")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert not mock_info.called  # B站 short-circuit: yt-dlp must not be called


def test_extract_falls_through_to_ytdlp_when_bilibili_empty(monkeypatch):
    """B站 returns no subtitles → fall through to yt-dlp path."""
    from services.summarizer import SubtitleExtractor

    empty_bili = {
        "has_subtitle": False, "language": "", "subtitle_type": "none",
        "is_target_language": True, "fallback_mode": None, "segments": [], "full_text": "",
    }
    fake_info = {
        "subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {},
    }
    monkeypatch.setattr("services.summarizer._extract_bilibili", lambda url: empty_bili)
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": f"yt-{lang}"}],
    )

    result = SubtitleExtractor().extract("https://www.bilibili.com/video/BV1xx-no-sub", language="zh")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert result["full_text"] == "yt-zh-Hans"


def test_extract_falls_back_to_ytdlp_for_non_bilibili(monkeypatch):
    """YouTube URLs go through yt-dlp; subtitles selected by priority."""
    from services.summarizer import SubtitleExtractor

    fake_info = {
        "subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {"en": [{"ext": "vtt", "url": "u2"}]},
    }
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": f"text-{lang}"}],
    )

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx", language="zh")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert result["is_target_language"] is True
    assert result["full_text"] == "text-zh-Hans"


def test_extract_no_subtitles_anywhere_returns_metadata_fallback(monkeypatch):
    """No subtitles + no metadata at all → has_subtitle=False, fallback_mode=None (caller decides)."""
    from services.summarizer import SubtitleExtractor

    fake_info = {"subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx")
    assert result["has_subtitle"] is False
    assert result["language"] == ""
    assert result["full_text"] == ""


def test_extract_truncates_full_text_to_15000_chars(monkeypatch):
    from services.summarizer import SubtitleExtractor

    long_text = "x" * 20000
    fake_info = {
        "subtitles": {"zh": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {},
    }
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": long_text}],
    )

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx", language="zh")
    assert len(result["full_text"]) == 15000


def test_build_summarizer_raises_without_api_key_when_not_mock(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import build_summarizer
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_summarizer()


def test_build_summarizer_returns_mock_when_env_set(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "true")

    from services.summarizer import build_summarizer, MockSummarizer
    s = build_summarizer()
    assert isinstance(s, MockSummarizer)


def test_build_summarizer_returns_real_with_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import build_summarizer, VideoSummarizer
    s = build_summarizer()
    assert isinstance(s, VideoSummarizer)


class FakeChunk:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})()]


class FakeStreamingResponse:
    def __init__(self, tokens):
        self._tokens = tokens

    def __iter__(self):
        return iter([FakeChunk(t) for t in self._tokens])


def test_summarize_stream_yields_all_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MODEL", "fake-model")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    s.client.chat.completions.create = lambda **kwargs: FakeStreamingResponse(["Hi", " there", "!"])

    tokens = list(s.summarize_stream("subtitle text here", "zh"))
    assert "".join(tokens) == "Hi there!"


def test_summarize_stream_uses_standard_prompt_for_subtitles(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["model"] = kwargs.get("model")
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕内容", "zh", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    assert "视频概述" in prompt
    assert "视频大纲" in prompt
    assert "字幕内容" in prompt


def test_summarize_stream_uses_fallback_prompt_without_subtitles(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("video title here", "zh", has_subtitle=False, video_meta={"title": "X", "duration": 600}))
    prompt = captured["messages"][1]["content"]
    assert "没有可用的字幕" in prompt
    assert "X" in prompt


def test_summarize_stream_uses_english_hint_when_language_not_zh(monkeypatch):
    """I1: language='en' should use '与原文相同的语言' instead of '中文'."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("English subtitles", "en", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    assert "与原文相同的语言" in prompt
    assert "中文" not in prompt


def test_summarize_stream_fallback_handles_none_video_meta(monkeypatch):
    """I2: video_meta=None should produce '（未知）' sentinels for title/platform."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("placeholder", "zh", has_subtitle=False, video_meta=None))
    prompt = captured["messages"][1]["content"]
    assert "没有可用的字幕" in prompt
    assert "（未知）" in prompt


def test_summarize_stream_uses_chinese_system_prompt(monkeypatch):
    """I3: messages[0] should be a system message with the Chinese assistant persona."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕", "zh", has_subtitle=True))
    system_msg = captured["messages"][0]
    assert system_msg["role"] == "system"
    assert "视频内容分析助手" in system_msg["content"]


def test_summarize_stream_standard_prompt_is_distinct_from_mock_body(monkeypatch):
    """I4: assert distinct-header strings (not the same as MockSummarizer.BODY)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer, MockSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕内容", "zh", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    # "结构化深度总结" is unique to SUMMARY_PROMPT_STANDARD (not in MockSummarizer.BODY)
    assert "结构化深度总结" in prompt
    # Make sure we did NOT accidentally return the unformatted template
    # (note: SUMMARY_PROMPT_STANDARD intentionally has {{...}} which renders to {...} in
    # the JSON example, so we check the placeholders directly instead of bare braces)
    assert "{language}" not in prompt
    assert "{subtitle}" not in prompt
    assert "{duration}" not in prompt
    # Sanity: prompt is substantively different from mock body
    assert len(prompt) != len(MockSummarizer.BODY)


def test_standard_prompt_enforces_markdown_h2_headers():
    """Regression: MiMo previously emitted `1. 视频概述` instead of `## 视频概述`.
    Prompt must use `##` as the main section marker and explicitly forbid
    numbered-list style."""
    from services.summarizer import SUMMARY_PROMPT_STANDARD
    p = SUMMARY_PROMPT_STANDARD
    # Use `## ` (markdown H2) as the canonical main-section marker
    assert "## 视频概述" in p
    assert "## 视频大纲" in p
    assert "## 总结" in p
    # Must contain a full JSON example with the correct outer braces
    assert '{{"outline":' in p
    # Must explicitly forbid the wrong style so the LLM sees a DO/DON'T
    assert "不要" in p  # "do not write 1. 视频概述"


def test_standard_prompt_has_full_output_example():
    """The prompt should embed a complete expected-output example so the LLM
    has a concrete shape to imitate (avoids the MiMo bug where it dropped
    section markers and the JSON outer braces)."""
    from services.summarizer import SUMMARY_PROMPT_STANDARD
    p = SUMMARY_PROMPT_STANDARD
    # The example block should show the exact "## 视频概述\n(...)" pattern
    assert "## 视频概述" in p
    assert "## 总结" in p
    assert "## 视频大纲" in p
    # The example should show a JSON code fence with the 2-level outline shape
    assert "```json" in p
    assert "{{\"outline\":" in p
    assert "{{\"timestamp\":" in p
    assert "\"part_outline\":" in p
    assert "\"content\":" in p


def test_summarize_stream_filters_none_and_empty_chunk_content(monkeypatch):
    """I5: chunks with None or '' content should be filtered out (OpenAI emits these)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    s.client.chat.completions.create = lambda **kwargs: FakeStreamingResponse(["", None, "Hi", None, " there", ""])

    tokens = list(s.summarize_stream("subtitle text", "zh"))
    assert "".join(tokens) == "Hi there"
    # No literal "None" string leaked through
    assert "None" not in "".join(tokens)


def test_mock_summarizer_streams_body_and_includes_json():
    from services.summarizer import MockSummarizer
    s = MockSummarizer()
    s.DELAY_MS = 0  # instant for test
    tokens = list(s.summarize_stream("ignored", "zh"))
    body = "".join(tokens)
    assert "## 视频概述" in body
    assert '"outline"' in body
    assert '"part_outline"' in body
    assert body.endswith("```\n")


from services.summarizer import parse_outline_json


def test_parse_outline_json_valid():
    body = (
        "## 视频概述\nhi\n"
        "```json\n"
        '{"outline": [{"title": "开场", "timestamp": 0, "part_outline": [{"timestamp": 5, "content": "要点1"}]}, '
        '{"title": "中段", "timestamp": 90, "part_outline": [{"timestamp": 95, "content": "要点2"}]}]}\n'
        "```\n"
    )
    md, outline = parse_outline_json(body)
    assert "## 视频概述" in md
    assert "```json" not in md
    assert len(outline) == 2
    assert outline[0]["title"] == "开场"
    assert outline[0]["timestamp"] == 0
    assert outline[0]["part_outline"] == [{"timestamp": 5, "content": "要点1"}]
    assert outline[1]["title"] == "中段"
    assert outline[1]["timestamp"] == 90


def test_parse_outline_json_no_json_block():
    body = "## 视频概述\nno outline here"
    md, outline = parse_outline_json(body)
    assert md == body
    assert outline == []


def test_parse_outline_json_invalid_returns_empty(caplog):
    import logging
    body = "## 视频概述\n```json\n{this is not valid json}\n```\n"
    with caplog.at_level(logging.WARNING):
        md, outline = parse_outline_json(body)
    assert "## 视频概述" in md
    assert outline == []
    assert "parse_outline_json" in caplog.text  # locks in the WARNING contract


def test_parse_outline_json_strips_preceding_markdown():
    body = (
        "Some intro\n```json\n"
        + json.dumps({"outline": [{"title": "x", "timestamp": 5, "part_outline": [{"timestamp": 5, "content": "a"}]}]})
        + "\n```"
    )
    md, outline = parse_outline_json(body)
    assert "Some intro" in md
    assert len(outline) == 1
    assert outline[0]["title"] == "x"


def test_parse_outline_json_coerces_types():
    """String timestamps from a sloppy LLM should be coerced to int."""
    body = (
        "```json\n"
        '{"outline": [{"title": "x", "timestamp": "30", "part_outline": '
        '[{"timestamp": "35", "content": "c"}, {"timestamp": "40", "content": "d"}]}]}\n'
        "```\n"
    )
    _, outline = parse_outline_json(body)
    assert len(outline) == 1
    assert outline[0]["timestamp"] == 30
    assert outline[0]["part_outline"][0]["timestamp"] == 35


def test_parse_outline_json_drops_empty_part_outline():
    """Sections with empty or missing part_outline are dropped (avoids empty
    chapter rows in the UI)."""
    body = (
        "```json\n"
        '{"outline": [\n'
        '  {"title": "ok", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "a"}]},\n'
        '  {"title": "empty_parts", "timestamp": 90, "part_outline": []},\n'
        '  {"title": "no_parts_key", "timestamp": 180}\n'
        ']}\n'
        "```\n"
    )
    _, outline = parse_outline_json(body)
    assert len(outline) == 1
    assert outline[0]["title"] == "ok"


def test_parse_outline_json_drops_malformed_sections():
    """Sections missing required fields (title, timestamp) are silently dropped."""
    body = (
        "```json\n"
        '{"outline": [\n'
        '  {"title": "ok", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "a"}]},\n'
        '  {"timestamp": 90, "part_outline": [{"timestamp": 90, "content": "b"}]},\n'
        '  {"title": "no_timestamp", "part_outline": [{"timestamp": 0, "content": "c"}]},\n'
        '  "not a dict"\n'
        ']}\n'
        "```\n"
    )
    _, outline = parse_outline_json(body)
    assert len(outline) == 1
    assert outline[0]["title"] == "ok"


