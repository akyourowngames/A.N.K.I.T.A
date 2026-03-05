"""
YouTube Connector for A.N.K.I.T.A 🎬

Gives ANKITA media library management superpowers:
  - get_subscriptions      : "Any new videos from Fireship?"
  - search_channel_videos  : "Find Python tutorials on Corey Schafer's channel"
  - create_playlist        : "Make a playlist of these 5 Python tutorials"
  - list_playlists         : "What playlists do I have?"
  - add_to_playlist        : "Add this video to my Lo-fi playlist"

Authentication: Google OAuth2 via auth_manager.get_google_credentials()
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_MISSING_LIBS = False
try:
    from googleapiclient.discovery import build
except ImportError:
    _MISSING_LIBS = True


def _youtube_service():
    """Build and return an authenticated YouTube Data API v3 service object."""
    if _MISSING_LIBS:
        raise RuntimeError(
            "Google API libraries not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )
    from tools.auth_manager import get_google_credentials
    creds = get_google_credentials()
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Public API functions (called by engine.py dispatcher)
# ---------------------------------------------------------------------------

def get_subscriptions(max_results: int = 20) -> Dict[str, Any]:
    """
    Return the user's YouTube subscriptions with their latest video info.

    Args:
        max_results: Maximum number of subscriptions to return (default 20)

    Returns:
        {"status": "success", "subscriptions": [{"channel": ..., "channel_id": ...}, ...]}
    """
    try:
        svc = _youtube_service()
        result = (
            svc.subscriptions()
            .list(part="snippet", mine=True, maxResults=max_results, order="alphabetical")
            .execute()
        )
        items = result.get("items", [])
        subs = [
            {
                "channel":    item["snippet"]["title"],
                "channel_id": item["snippet"]["resourceId"]["channelId"],
                "description": item["snippet"].get("description", "")[:100],
            }
            for item in items
        ]
        return {"status": "success", "subscriptions": subs, "count": len(subs)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def search_channel_videos(channel_name: str, query: str = "", max_results: int = 10) -> Dict[str, Any]:
    """
    Search for videos by a channel name (resolves channel name → ID first).

    Args:
        channel_name: Channel name or handle, e.g. "Fireship" or "Corey Schafer"
        query: Optional search term within the channel
        max_results: Max number of videos to return (default 10)

    Returns:
        {"status": "success", "videos": [{"title": ..., "url": ..., "published": ...}, ...]}
    """
    try:
        svc = _youtube_service()

        # Step 1: Resolve channel name → channel ID
        ch_result = svc.search().list(
            part="snippet", q=channel_name, type="channel", maxResults=1
        ).execute()
        ch_items = ch_result.get("items", [])
        if not ch_items:
            return {"status": "error", "message": f"Channel '{channel_name}' not found."}
        channel_id = ch_items[0]["snippet"]["channelId"]

        # Step 2: Search videos within that channel
        search_params: Dict[str, Any] = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": max_results,
        }
        if query:
            search_params["q"] = query

        vid_result = svc.search().list(**search_params).execute()
        videos = [
            {
                "title":     item["snippet"]["title"],
                "video_id":  item["id"]["videoId"],
                "url":       f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "published": item["snippet"].get("publishedAt", ""),
                "channel":   item["snippet"].get("channelTitle", channel_name),
            }
            for item in vid_result.get("items", [])
        ]
        return {"status": "success", "channel": channel_name, "videos": videos, "count": len(videos)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_playlist(name: str, description: str = "", video_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Create a new YouTube playlist and optionally add videos to it.

    Args:
        name: Playlist name, e.g. "Python Tutorials 2026"
        description: Optional playlist description
        video_ids: Optional list of YouTube video IDs to add

    Returns:
        {"status": "success", "playlist_id": ..., "url": ..., "videos_added": N}
    """
    try:
        svc = _youtube_service()

        # Create the playlist
        playlist = (
            svc.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {"title": name, "description": description},
                    "status":  {"privacyStatus": "private"},
                },
            )
            .execute()
        )
        playlist_id = playlist["id"]
        videos_added = 0

        # Add videos if provided
        if video_ids:
            for vid_id in video_ids:
                try:
                    svc.playlistItems().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "playlistId": playlist_id,
                                "resourceId": {"kind": "youtube#video", "videoId": vid_id},
                            }
                        },
                    ).execute()
                    videos_added += 1
                except Exception:
                    pass  # Skip invalid video IDs

        return {
            "status":       "success",
            "playlist":     name,
            "playlist_id":  playlist_id,
            "url":          f"https://www.youtube.com/playlist?list={playlist_id}",
            "videos_added": videos_added,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_playlists(max_results: int = 20) -> Dict[str, Any]:
    """
    List the authenticated user's YouTube playlists.

    Args:
        max_results: Maximum number of playlists to return (default 20)

    Returns:
        {"status": "success", "playlists": [{"title": ..., "id": ..., "url": ...}, ...]}
    """
    try:
        svc = _youtube_service()
        result = (
            svc.playlists()
            .list(part="snippet,contentDetails", mine=True, maxResults=max_results)
            .execute()
        )
        playlists = [
            {
                "title":       item["snippet"]["title"],
                "playlist_id": item["id"],
                "url":         f"https://www.youtube.com/playlist?list={item['id']}",
                "video_count": item["contentDetails"]["itemCount"],
            }
            for item in result.get("items", [])
        ]
        return {"status": "success", "playlists": playlists, "count": len(playlists)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def add_to_playlist(playlist_id: str, video_id: str) -> Dict[str, Any]:
    """
    Add a single video to an existing playlist.

    Args:
        playlist_id: The YouTube playlist ID
        video_id: The YouTube video ID to add

    Returns:
        {"status": "success", "playlist_id": ..., "video_id": ...}
    """
    try:
        svc = _youtube_service()
        svc.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
        return {
            "status":      "success",
            "playlist_id": playlist_id,
            "video_id":    video_id,
            "video_url":   f"https://www.youtube.com/watch?v={video_id}",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
