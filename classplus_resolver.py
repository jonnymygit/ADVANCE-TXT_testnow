# classplus_resolver.py
import asyncio
import requests
import logging
from io import BytesIO
from typing import Optional
from yt_dlp import YoutubeDL
import concurrent.futures

logger = logging.getLogger(__name__)

# ----- Synchronous helpers (wrapped into async) -----

def _extract_with_ytdlp(url: str, timeout: int = 30) -> Optional[str]:
    """
    Use yt-dlp to extract a direct playable URL from the provided URL.
    Returns a direct URL (often to an mp4 or .m3u8) or None.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "forcejson": True,
        # restrict filenames, avoid writing files
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.debug("yt-dlp extraction failed: %s", e)
        return None

    # If playlist/entries, pick first entry
    if isinstance(info, dict) and info.get("entries"):
        entry = info["entries"][0]
    else:
        entry = info

    # Prefer format with http(s) and ext in (mp4, m4a, webm, m3u8)
    formats = entry.get("formats") or []
    if not formats:
        # some extractors put direct url in 'url'
        direct = entry.get("url")
        if direct:
            return direct
        return None

    # choose best candidate: prefer mp4/m3u8 and https
    candidates = []
    for f in formats:
        f_url = f.get("url")
        if not f_url:
            continue
        ext = f.get("ext", "").lower()
        protocol = f.get("protocol", "").lower()
        score = 0
        if protocol.startswith("https"):
            score += 2
        if ext in ("mp4", "m4a", "webm", "m3u8"):
            score += 2
        # prefer higher bitrate/height if available
        if f.get("tbr"):
            score += int(min(f["tbr"], 10000) / 1000)
        if f.get("height"):
            score += int(min(f["height"], 2160) / 360)
        candidates.append((score, f_url))

    if not candidates:
        return None

    candidates.sort(reverse=True, key=lambda x: x[0])
    best_url = candidates[0][1]
    return best_url


def _call_classplus_api(url: str, timeout: int = 15) -> Optional[str]:
    """
    Try the Classplus jw-signed-url API endpoint as a fallback.
    We don't hardcode tokens; we try a minimal request and accept whatever response returns.
    """
    api = "https://api.classplusapp.com/cams/uploader/video/jw-signed-url"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; resolver/1.0)",
        "Accept": "application/json",
    }
    try:
        resp = requests.get(api, params={"url": url}, headers=headers, timeout=timeout)
        # If the API returns JSON with 'url' key, return it
        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("url"):
                    return data["url"]
            except Exception:
                # not JSON or parse error
                logger.debug("Classplus API returned non-json or missing 'url': %s", resp.text[:200])
                return None
        else:
            logger.debug("Classplus API returned HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.debug("Classplus API call failed: %s", e)
    return None


def _probe_head(url: str, timeout: int = 10) -> bool:
    """
    Quick HEAD probe to see if the URL is reachable and looks like media.
    Returns True if content-type suggests media.
    """
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
    except Exception:
        try:
            # some servers don't support HEAD; fallback to GET with Range request
            resp = requests.get(url, stream=True, timeout=timeout, headers={"Range": "bytes=0-1024"})
        except Exception as e:
            logger.debug("probe failed: %s", e)
            return False

    ctype = resp.headers.get("Content-Type", "").lower()
    if any(x in ctype for x in ("video", "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio", "application/dash+xml")):
        return True
    return False


# ----- Async wrapper API -----

async def resolve_classplus_url(original_url: str, timeout: int = 40) -> str:
    """
    Resolve an input Classplus (or similar) URL to a usable media URL.
    Tries:
      1) yt-dlp extraction
      2) Classplus jw-signed-url API
      3) direct probe of original url
    Returns a URL string on success or raises RuntimeError on failure.
    """
    loop = asyncio.get_running_loop()
    # 1) yt-dlp (run in threadpool because it's blocking)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            result = await loop.run_in_executor(ex, _extract_with_ytdlp, original_url)
        if result:
            logger.info("resolve_classplus_url: resolved via yt-dlp")
            return result
    except Exception as e:
        logger.debug("yt-dlp step exception: %s", e)

    # 2) call classplus api
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            api_result = await loop.run_in_executor(ex, _call_classplus_api, original_url)
        if api_result:
            logger.info("resolve_classplus_url: resolved via Classplus API")
            return api_result
    except Exception as e:
        logger.debug("Classplus API step exception: %s", e)

    # 3) Probe original URL directly
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ok = await loop.run_in_executor(ex, _probe_head, original_url)
        if ok:
            logger.info("resolve_classplus_url: original URL appears to be media and reachable")
            return original_url
    except Exception as e:
        logger.debug("probe step exception: %s", e)

    # 4) Give up with debug info
    raise RuntimeError(f"Unable to resolve media URL for: {original_url}")

# Optional helper to download via yt-dlp into file (blocking, run in executor)
def download_with_yt_dlp(url: str, output_template: str, format_selection: str = "best") -> str:
    """
    Downloads the media using yt-dlp into a filename derived from output_template.
    Returns the local filename on success or raises on failure.
    """
    ydl_opts = {
        "format": format_selection,
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": True,
        # You might want to add retry options or external downloader
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # ydl will respect outtmpl; return generated filename if available
        filename = ydl.prepare_filename(info)
        return filename
