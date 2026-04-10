import os
import re
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


def _get_youtube():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        raise ValueError("YOUTUBE_API_KEY が設定されていません。env.example を参考に .env ファイルを作成してください。")
    return build("youtube", "v3", developerKey=api_key)


def _parse_duration(iso_duration: str) -> str:
    """ISO 8601 duration (PT1H2M3S) を 1:02:03 形式に変換する。"""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return "不明"
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _duration_seconds(iso_duration: str) -> int:
    """ISO 8601 duration を秒数に変換する。"""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _format_number(value) -> str:
    """数値を読みやすい形式にフォーマットする（例: 1234567 → 1,234,567）。"""
    if value is None:
        return "非公開"
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def _published_after_from_period(period: str) -> str | None:
    """期間文字列をRFC3339形式のpublishedAfter値に変換する。"""
    now = datetime.now(timezone.utc)
    delta_map = {
        "1month": timedelta(days=30),
        "2months": timedelta(days=60),
        "6months": timedelta(days=180),
        "1year": timedelta(days=365),
    }
    delta = delta_map.get(period)
    if delta is None:
        return None
    return (now - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def search_videos(query: str, max_results: int = 10, period: str = "all") -> list[dict]:
    """
    YouTube動画を検索し、詳細情報を含むリストを返す。

    Args:
        query: 検索キーワード
        max_results: 取得件数（1〜50）
        period: 期間フィルター（all / 1month / 2months / 6months / 1year）

    Returns:
        動画情報の辞書リスト
    """
    youtube = _get_youtube()
    max_results = max(1, min(50, max_results))

    # Step 1: search.list で video ID を取得
    search_params = dict(
        q=query,
        part="snippet",
        type="video",
        maxResults=max_results,
    )
    published_after = _published_after_from_period(period)
    if published_after:
        search_params["publishedAfter"] = published_after

    search_response = youtube.search().list(**search_params).execute()

    items = search_response.get("items", [])
    if not items:
        return []

    video_ids = [item["id"]["videoId"] for item in items]

    # Step 2: videos.list で詳細情報を一括取得
    videos_response = youtube.videos().list(
        id=",".join(video_ids),
        part="snippet,statistics,contentDetails",
    ).execute()

    video_map = {v["id"]: v for v in videos_response.get("items", [])}

    # Step 3: channels.list でチャンネル登録者数を取得
    channel_ids = list({
        v["snippet"]["channelId"]
        for v in video_map.values()
        if "channelId" in v.get("snippet", {})
    })

    channel_map = {}
    if channel_ids:
        channels_response = youtube.channels().list(
            id=",".join(channel_ids),
            part="statistics",
        ).execute()
        for ch in channels_response.get("items", []):
            channel_map[ch["id"]] = ch.get("statistics", {})

    # Step 4: 結果を整形
    results = []
    for vid_id in video_ids:
        video = video_map.get(vid_id)
        if not video:
            continue

        snippet = video.get("snippet", {})
        stats = video.get("statistics", {})
        content = video.get("contentDetails", {})
        channel_id = snippet.get("channelId", "")
        ch_stats = channel_map.get(channel_id, {})

        published_at = snippet.get("publishedAt", "")
        if published_at:
            published_at = published_at[:10]  # YYYY-MM-DD

        iso_duration = content.get("duration", "")
        dur_sec = _duration_seconds(iso_duration)

        raw_views = int(stats["viewCount"]) if stats.get("viewCount") else 0
        raw_subs = int(ch_stats["subscriberCount"]) if ch_stats.get("subscriberCount") else 0

        results.append({
            "video_id": vid_id,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "thumbnail": (
                snippet.get("thumbnails", {})
                .get("medium", {})
                .get("url", "")
            ),
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "tags": snippet.get("tags", []),
            "published_at": published_at,
            "channel_name": snippet.get("channelTitle", ""),
            "channel_id": channel_id,
            "subscriber_count": _format_number(ch_stats.get("subscriberCount")),
            "subscriber_count_raw": raw_subs,
            "view_count": _format_number(stats.get("viewCount")),
            "view_count_raw": raw_views,
            "like_count": _format_number(stats.get("likeCount")),
            "comment_count": _format_number(stats.get("commentCount")),
            "duration": _parse_duration(iso_duration),
            "duration_seconds": dur_sec,
        })

    return results
