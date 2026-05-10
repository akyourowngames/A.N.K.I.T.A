from __future__ import annotations

from typing import Any


def media_play(target: Any) -> dict[str, Any]:
    result = target.evaluate(
        """
        async () => {
        """
        + MEDIA_HELPERS
        + """
          const media = document.querySelector("video, audio");
          if (!media) {
            return {ok: false, summary: "No accessible HTML media element found.", state: mediaState(), embedded_players: embeddedPlayers()};
          }
          try {
            await media.play();
            return {ok: true, summary: "Media playback requested.", state: mediaState(), embedded_players: embeddedPlayers()};
          } catch (error) {
            return {ok: false, summary: String(error && error.message ? error.message : error), state: mediaState(), embedded_players: embeddedPlayers()};
          }
        }
        """
    )
    return normalize_result(result)


def media_control(target: Any, params: dict[str, Any]) -> dict[str, Any]:
    action = str(params.get("action") or "").strip()
    result = target.evaluate(
        """
        async (input) => {
        """
        + MEDIA_HELPERS
        + """
          const media = document.querySelector("video, audio");
          if (!media) {
            return {ok: false, summary: "No accessible HTML media element found.", state: mediaState(), embedded_players: embeddedPlayers()};
          }
          try {
            if (input.action === "play") {
              await media.play();
            } else if (input.action === "pause") {
              media.pause();
            } else if (input.action === "seek") {
              media.currentTime = Number(input.seconds || 0);
            } else if (input.action === "volume") {
              media.volume = Math.max(0, Math.min(1, Number(input.volume || 0)));
            } else if (input.action === "speed") {
              media.playbackRate = Math.max(0.1, Math.min(16, Number(input.speed || 1)));
            } else if (input.action === "fullscreen") {
              if (media.requestFullscreen) {
                await media.requestFullscreen();
              }
            } else {
              return {ok: false, summary: "Unsupported media action.", state: mediaState(), embedded_players: embeddedPlayers()};
            }
            return {ok: true, summary: "Media control applied.", action: input.action, state: mediaState(), embedded_players: embeddedPlayers()};
          } catch (error) {
            return {ok: false, summary: String(error && error.message ? error.message : error), action: input.action, state: mediaState(), embedded_players: embeddedPlayers()};
          }
        }
        """,
        {
            "action": action,
            "seconds": params.get("seconds"),
            "volume": params.get("volume"),
            "speed": params.get("speed"),
        },
    )
    return normalize_result(result)


def media_state(target: Any) -> dict[str, Any]:
    result = target.evaluate(
        """
        () => {
        """
        + MEDIA_HELPERS
        + """
          return {summary: "Media state read.", state: mediaState(), embedded_players: embeddedPlayers()};
        }
        """
    )
    return normalize_result(result)


def media_extract(target: Any) -> dict[str, Any]:
    result = target.evaluate(
        """
        () => {
        """
        + MEDIA_HELPERS
        + """
          const meta = {};
          for (const item of Array.from(document.querySelectorAll("meta[property], meta[name]"))) {
            const key = item.getAttribute("property") || item.getAttribute("name") || "";
            const value = item.getAttribute("content") || "";
            if (key && value && Object.keys(meta).length < 50) {
              meta[key] = value;
            }
          }
          return {
            summary: "Media metadata extracted.",
            title: document.title || "",
            metadata: meta,
            state: mediaState(),
            embedded_players: embeddedPlayers()
          };
        }
        """
    )
    return normalize_result(result)


def normalize_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"summary": "Media operation returned no structured result.", "raw": value}


MEDIA_HELPERS = """

function mediaState() {
  const media = Array.from(document.querySelectorAll("video, audio")).map((item, index) => ({
    index,
    tag: item.tagName.toLowerCase(),
    current_time: Number(item.currentTime || 0),
    duration: Number(item.duration || 0),
    paused: Boolean(item.paused),
    playing: Boolean(!item.paused && !item.ended),
    ended: Boolean(item.ended),
    muted: Boolean(item.muted),
    volume: Number(item.volume || 0),
    playback_rate: Number(item.playbackRate || 1),
    buffered: bufferedRanges(item),
    src: item.currentSrc || item.src || "",
    tracks: Array.from(item.textTracks || []).map((track) => ({
      kind: track.kind || "",
      label: track.label || "",
      language: track.language || "",
      mode: track.mode || ""
    }))
  }));
  return {
    media,
    fullscreen: Boolean(document.fullscreenElement)
  };
}

function bufferedRanges(item) {
  const ranges = [];
  for (let index = 0; index < item.buffered.length; index += 1) {
    ranges.push({start: item.buffered.start(index), end: item.buffered.end(index)});
  }
  return ranges;
}

function embeddedPlayers() {
  return Array.from(document.querySelectorAll("iframe, embed, object")).slice(0, 50).map((item, index) => ({
    index,
    tag: item.tagName.toLowerCase(),
    title: item.getAttribute("title") || "",
    src: item.getAttribute("src") || item.getAttribute("data") || "",
    allow: item.getAttribute("allow") || "",
    width: item.getAttribute("width") || "",
    height: item.getAttribute("height") || ""
  }));
}
"""
