#!/usr/bin/env python3
from flask import Flask, render_template, request, redirect, send_file
from ytmusicapi import YTMusic
import yt_dlp
import logging
import os
import threading
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, ID3NoHeaderError, APIC
from PIL import Image
from io import BytesIO
import requests
from datetime import datetime, timedelta
from collections import defaultdict
import time
import shutil
import json

app = Flask(__name__)
ytmusic = YTMusic()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config Path
CONFIG_PATH = Path(__file__).with_name("config.json")
_CONFIG = {}
if CONFIG_PATH.exists():
    try:
        _CONFIG = json.loads(CONFIG_PATH.read_text())
    except Exception:
        logger.warning(f"Failed to parse config.json at {CONFIG_PATH}")


def _cfg_get(key, default=None):
    return os.environ.get(key.upper(), _CONFIG.get(key, default))


CACHE_DIR = Path(_cfg_get("cache_dir", str(Path(__file__).parent / "audio_cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Enable/disable embedding cover art (APIC)
ENABLE_COVER = True

DOWNLOAD_LOCKS = defaultdict(lambda: threading.Lock())
DOWNLOAD_IN_PROGRESS = set()

SONG_CACHE = {}
SONG_CACHE_TTL = 300

DEFAULT_YDL_EXTRACTOR_ARGS = {"youtube": {"player_client": "default"}}


def get_song_details(video_id):
    """Return cached ytmusic.get_song result when available and fresh, else fetch and cache."""
    now = time.time()
    entry = SONG_CACHE.get(video_id)
    if entry:
        ts, data = entry
        if now - ts < SONG_CACHE_TTL:
            return data

    try:
        data = ytmusic.get_song(video_id)
        SONG_CACHE[video_id] = (now, data)
        return data
    except Exception as e:
        logger.warning(f"ytmusic.get_song failed for {video_id}: {e}")
        # Cache negative result briefly to avoid repeated failures
        SONG_CACHE[video_id] = (now, None)
        return None


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe filename (keep spaces, -, _)."""
    if not name:
        return ""
    name = str(name).strip()
    name = " ".join(name.split())
    return "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).rstrip()


def make_filename(title: str, artists: str) -> str:
    """Return sanitized 'title - artists.mp3' filename."""
    t = sanitize_filename(title) if title else ""
    a = sanitize_filename(artists) if artists else ""
    if a and t:
        return f"{t} - {a}.mp3"
    if t:
        return f"{t}.mp3"
    return f"{artists or 'unknown'}.mp3"


def format_artists(artists):
    """Extract artist names from song data and return a single string."""
    if not artists:
        return ""
    names = []
    for a in artists:
        if isinstance(a, dict):
            n = a.get("name") or a.get("artist") or a.get("browseId") or ""
            if n:
                names.append(n)
        else:
            names.append(str(a))
    return ", ".join(names)


def make_psp_cover(url):
    """Download cover image, center-crop to square, resize to 150x150 and return JPEG bytes."""
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logger.warning(f"Cover download failed: HTTP {r.status_code}")
            return None

        img = Image.open(BytesIO(r.content)).convert("RGB")

        # center crop to square
        w, h = img.size
        if w != h:
            if w > h:
                offset = (w - h) // 2
                img = img.crop((offset, 0, offset + h, h))
            else:
                offset = (h - w) // 2
                img = img.crop((0, offset, w, offset + w))

        # resize to PSP safe size
        img = img.resize((150, 150), Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
        # ensure not too large for PSP: if > 60KB, re-save smaller
        if len(data) > 60 * 1024:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=70)
            data = buf.getvalue()
        return data

    except Exception as e:
        logger.error(f"Cover conversion error: {e}")
        return None


def add_metadata(audio_path, song_info, ytdlp_info=None):
    """Add metadata (title, artist, album, year) and optionally APIC cover.
    Does NOT clear essential ID3 header frames to keep MP3 integrity for PSP."""
    try:
        # load existing tags or create header
        try:
            id3 = ID3(str(audio_path))
        except ID3NoHeaderError:
            id3 = ID3()

        # Title resolution (priority: ytmusic -> ytdlp -> filename)
        title = None
        if song_info:
            title = song_info.get("title")
        if not title and ytdlp_info:
            title = ytdlp_info.get("title")
        if not title:
            title = audio_path.stem

        # Replace or add title
        try:
            id3.add(TIT2(encoding=3, text=title))
        except Exception:
            pass

        # Artists resolution
        artists_list = []
        if song_info and "artists" in song_info:
            for a in song_info["artists"]:
                if isinstance(a, dict):
                    nm = a.get("name") or a.get("artist")
                    if nm:
                        artists_list.append(nm)
                else:
                    artists_list.append(str(a))

        if (not artists_list) and ytdlp_info:
            a = (
                ytdlp_info.get("artist")
                or ytdlp_info.get("uploader")
                or ytdlp_info.get("uploader_id")
            )
            if a:
                artists_list = [a]

        if not artists_list:
            artists_list = ["Unknown Artist"]

        try:
            id3.add(TPE1(encoding=3, text=artists_list))
        except Exception:
            pass

        # Album
        album = ""
        if song_info and song_info.get("album"):
            if isinstance(song_info["album"], dict):
                album = song_info["album"].get("name", "")
            else:
                album = str(song_info["album"])
        if not album and ytdlp_info:
            album = ytdlp_info.get("album") or ytdlp_info.get("release")
        if album:
            try:
                id3.add(TALB(encoding=3, text=album))
            except Exception:
                pass

        # Year
        year = ""
        if song_info and song_info.get("year"):
            year = str(song_info.get("year"))
        if not year and ytdlp_info:
            ud = ytdlp_info.get("upload_date")
            if ud and len(ud) >= 4:
                year = ud[:4]
        if year:
            try:
                id3.add(TYER(encoding=3, text=year))
            except Exception:
                pass

        # COVER ART (PSP safe) - place before save
        if ENABLE_COVER and ytdlp_info:
            cover_url = None
            if "thumbnail" in ytdlp_info and ytdlp_info["thumbnail"]:
                cover_url = ytdlp_info["thumbnail"]
            if not cover_url and song_info:
                if isinstance(song_info.get("thumbnails"), list) and song_info.get(
                    "thumbnails"
                ):
                    cover_url = song_info["thumbnails"][-1].get("url")
                elif song_info.get("videoDetails", {}).get("thumbnail"):
                    cover_url = song_info.get("videoDetails", {}).get("thumbnail")

            if cover_url:
                cover_data = make_psp_cover(cover_url)
                if cover_data:
                    try:
                        id3.add(
                            APIC(
                                encoding=3,
                                mime="image/jpeg",
                                type=3,  # front cover
                                desc="Cover",
                                data=cover_data,
                            )
                        )
                    except Exception as e:
                        logger.warning(f"APIC add failed: {e}")

        # Save tags
        try:
            id3.save(str(audio_path))
            logger.info(f"Metadata successfully written → {audio_path}")
        except Exception as e:
            logger.error(f"Failed to save ID3 tags: {e}")

    except Exception as e:
        logger.error(f"Metadata error: {e}")


def get_fallback_meta_from_yt(video_id):
    """Use yt_dlp to fetch basic metadata (title/uploader) as fallback"""
    try:
        ydl_opts = {"quiet": True}
        ydl_opts.setdefault("extractor_args", DEFAULT_YDL_EXTRACTOR_ARGS)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
            title = info.get("title") or info.get("display_id") or f"{video_id}"
            uploader = info.get("uploader") or info.get("uploader_id") or ""
            artists = uploader if uploader else "Unknown Artist"
            return {"title": title, "artists": [{"name": artists}]}
    except Exception as e:
        logger.warning(f"yt_dlp fallback meta failed for {video_id}: {e}")
        return {"title": video_id, "artists": []}


def cleanup_old_files():
    """Remove files older than 10 minutes"""
    try:
        current_time = datetime.now()
        deleted_count = 0

        for file_path in CACHE_DIR.glob("*.mp3"):
            file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            if current_time - file_time > timedelta(minutes=10):
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.info(f"Cleaned up old file: {file_path.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old files")

    except Exception as e:
        logger.error(f"Cleanup error: {e}")


def resolve_title_and_artists(video_id, song_details):
    """Return (title, artists_str) with strong fallbacks (never Unknown Artist)."""
    title = None
    artists = []

    # YTMusic primary
    if song_details:
        title = song_details.get("title") or (
            song_details.get("videoDetails") or {}
        ).get("title")
        if "artists" in song_details and song_details["artists"]:
            for a in song_details["artists"]:
                if isinstance(a, dict):
                    n = a.get("name")
                    if n:
                        artists.append(n)
                else:
                    artists.append(str(a))

        # fallback to videoDetails author
        if not artists:
            vd = song_details.get("videoDetails", {})
            author = vd.get("author") if vd else None
            if author:
                artists = [author]

    # yt-dlp fallback
    if not artists or not title:
        try:
            tmp_opts = {"quiet": True}
            tmp_opts.setdefault("extractor_args", DEFAULT_YDL_EXTRACTOR_ARGS)
            with yt_dlp.YoutubeDL(tmp_opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=False
                )
                if not title:
                    title = info.get("title")
                fallback_artist = (
                    info.get("artist")
                    or info.get("uploader")
                    or info.get("uploader_id")
                    or info.get("creator")
                    or info.get("channel")
                    or info.get("channel_id")
                )
                if fallback_artist:
                    if isinstance(fallback_artist, list):
                        # sometimes artist is list
                        artists = [str(x) for x in fallback_artist if x]
                    else:
                        artists = [fallback_artist]
        except Exception:
            pass

    # ultimate fallback
    if not artists:
        artists = ["Unknown Artist"]
    if not title:
        title = video_id

    return title, ", ".join(artists)


def download_audio(video_id, song_info):
    """Download audio as MP3 with proper metadata and safe filename.
    Uses per-video lock and polling to avoid race conditions with yt-dlp/ffmpeg."""
    logger.info(f"[DOWNLOAD] Start download_audio for {video_id}")

    # ensure cache dir exists
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"[DOWNLOAD] Cannot create CACHE_DIR: {e}")
        return None

    lock = DOWNLOAD_LOCKS[video_id]
    acquired = lock.acquire(timeout=30)  # avoid deadlock
    if not acquired:
        logger.error(f"[DOWNLOAD] Could not acquire lock for {video_id}")
        return None

    try:
        # Use resolver to get consistent title & artist string
        title, artists_str = resolve_title_and_artists(video_id, song_info)

        final_filename = make_filename(title, artists_str)
        final_path = CACHE_DIR / final_filename

        if final_path.exists():
            logger.info(
                f"[DOWNLOAD] Using cached file (found before start): {final_filename}"
            )
            return str(final_path)

        # mark in-progress
        DOWNLOAD_IN_PROGRESS.add(video_id)

        temp_pattern = str(CACHE_DIR / f"{video_id}.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": temp_pattern,
            "quiet": True,
            "writethumbnail": False,
            "keepvideo": False,
            "overwrites": True,
            "windowsfilenames": False,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                    "nopostoverwrites": False,
                }
            ],
            "postprocessor_args": {"FFmpegExtractAudio": ["-y"]},
        }
        # ffmpeg_location can be overridden by env FFMPEG_LOCATION or config.json 'ffmpeg_location'
        ffmpeg_path = _cfg_get("ffmpeg_location", shutil.which("ffmpeg"))
        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(ffmpeg_path)

        logger.info(f"[DOWNLOAD] Running yt-dlp for {video_id}")
        info = None
        try:
            # prefer extractor args to reduce missing-format warnings when JS runtime isn't present
            ydl_opts.setdefault("extractor_args", DEFAULT_YDL_EXTRACTOR_ARGS)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=True
                )
        except Exception as e:
            logger.error(f"[DOWNLOAD] yt-dlp failed for {video_id}: {e}")
            return None

        # After yt-dlp returns, poll for produced mp3
        mp3_path = None
        poll_attempts = 30
        for attempt in range(poll_attempts):
            try:
                mp3_candidates = sorted(
                    CACHE_DIR.glob(f"{video_id}*.mp3"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            except Exception:
                mp3_candidates = []
            if mp3_candidates:
                mp3_path = mp3_candidates[0]
                if mp3_path.exists():
                    break
            time.sleep(0.15)

        # last-ditch try: maybe ydl.prepare_filename gives us name (with .mp3)
        if (not mp3_path or not mp3_path.exists()) and info is not None:
            try:
                with yt_dlp.YoutubeDL({}) as tmpydl:
                    prepared = Path(tmpydl.prepare_filename(info)).with_suffix(".mp3")
                    if prepared.exists():
                        mp3_path = prepared
            except Exception:
                mp3_path = mp3_path

        if not mp3_path or not mp3_path.exists():
            logger.error(
                f"[DOWNLOAD] No mp3 produced for {video_id}. Listing cache: {list(CACHE_DIR.glob('*'))}"
            )
            return None

        logger.info(f"[DOWNLOAD] Temp MP3 located: {mp3_path.name}")

        # Move atomically to final name
        try:
            os.replace(str(mp3_path), str(final_path))
            logger.info(
                f"[DOWNLOAD] Atomically moved {mp3_path.name} -> {final_filename}"
            )
        except Exception as e:
            logger.warning(
                f"[DOWNLOAD] os.replace failed ({e}), fallback to shutil.move"
            )
            try:
                shutil.move(str(mp3_path), str(final_path))
            except Exception as e2:
                logger.error(f"[DOWNLOAD] move fallback failed: {e2}")
                return None

        # Clean leftover temp files
        try:
            for p in CACHE_DIR.glob(f"{video_id}*"):
                try:
                    if p.exists() and p != final_path:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass

        # Now write clean metadata; wrap in try/catch
        try:
            add_metadata(final_path, song_info, info)
        except Exception as e:
            logger.error(f"[DOWNLOAD] add_metadata failed: {e}")

        logger.info(f"[DOWNLOAD] Completed successfully → {final_filename}")
        return str(final_path)

    finally:
        # release in-progress mark and lock
        DOWNLOAD_IN_PROGRESS.discard(video_id)
        try:
            lock.release()
        except Exception:
            pass


@app.route("/")
def index():
    """Main search page optimized for PSP"""
    # Run cleanup on home page access
    threading.Thread(target=cleanup_old_files, daemon=True).start()

    return render_template("index.html")


@app.route("/search")
def search():
    """Search for songs"""
    query = request.args.get("q", "").strip()
    if not query:
        return redirect("/")

    try:
        search_results = ytmusic.search(query, filter="songs", limit=12)

        # Process results
        processed_results = []
        for song in search_results:
            if "videoId" in song and ("title" in song or song.get("title")):
                processed_results.append(
                    {
                        "videoId": song["videoId"],
                        "title": song.get("title")
                        or song.get("videoDetails", {}).get("title", song["videoId"]),
                        "artists": format_artists(song.get("artists", [])),
                        "duration": song.get("duration", ""),
                        "album": (
                            song.get("album", {}).get("name", "")
                            if song.get("album")
                            else ""
                        ),
                    }
                )

        return render_template(
            "search_results.html", query=query, results=processed_results
        )

    except Exception as e:
        return render_template("error.html", message=f"Search failed: {str(e)}")


@app.route("/web_player/<video_id>")
def web_player(video_id):
    """Web player for normal browsers"""

    try:
        # Use cached song details helper (reduces repeated network calls)
        song_details = get_song_details(video_id)
        title, artists = resolve_title_and_artists(video_id, song_details)

        # Get audio URL for streaming
        ydl_opts = {"format": "bestaudio/best", "quiet": True}
        ydl_opts.setdefault("extractor_args", DEFAULT_YDL_EXTRACTOR_ARGS)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
            audio_url = info.get("url")

        return render_template(
            "web_player.html",
            title=title,
            artists=artists,
            audio_url=audio_url,
            video_id=video_id,
        )

    except Exception as e:
        return render_template("error.html", message=f"Player error: {str(e)}")


@app.route("/psp_download/<video_id>")
def psp_download(video_id):
    """PSP download page"""

    try:
        # Use cached helper to reduce repeated ytmusic calls
        song_details = get_song_details(video_id)
        title, artists = resolve_title_and_artists(video_id, song_details)

        # If already downloading, don't spawn another thread
        if video_id in DOWNLOAD_IN_PROGRESS:
            logger.info(
                f"[PSP_DOWNLOAD] {video_id} already in progress, not spawning new thread"
            )
        else:
            # If cached exists, skip spawn
            final_filename = make_filename(title, artists)
            if (CACHE_DIR / final_filename).exists():
                logger.info(
                    f"[PSP_DOWNLOAD] Cached exists for {video_id}, skipping spawn"
                )
            else:
                # spawn background thread to download
                threading.Thread(
                    target=download_audio, args=(video_id, song_details), daemon=True
                ).start()

        return render_template("psp_download.html", title=title, video_id=video_id)

    except Exception as e:
        return render_template("error.html", message=f"Download error: {str(e)}"), 500


@app.route("/psp_download_final/<video_id>")
def psp_download_final(video_id):
    """Final download page"""
    try:
        # Use cached helper to reduce repeated ytmusic calls
        song_details = get_song_details(video_id)
        title, artists = resolve_title_and_artists(video_id, song_details)

        # Get the actual filename using Title - Artist
        filename = make_filename(title, artists)
        audio_path = CACHE_DIR / filename

        # If file not present, wait a bit for the background worker to finish (poll)
        if not audio_path.exists():
            waited = 0.0
            while waited < 5.0:
                if audio_path.exists():
                    break
                time.sleep(0.2)
                waited += 0.2

        if not audio_path.exists():
            # Try to synchronously download as last resort (this will acquire locks)
            new_path = download_audio(video_id, song_details)
            if new_path:
                audio_path = Path(new_path)

        if not audio_path.exists():
            return render_template(
                "error.html", message="Download failed. Please try again."
            )

        file_size = audio_path.stat().st_size // 1024  # Size in KB

        # Try to read MP3 bitrate (in kbps) using mutagen; fall back to generic label
        bitrate_display = None
        try:
            mp3_info = MP3(str(audio_path))
            bitrate = getattr(mp3_info.info, "bitrate", None)
            if bitrate:
                bitrate_display = f"{bitrate // 1000} kbps"
        except Exception:
            bitrate_display = None

        format_display = f"MP3 ({bitrate_display})" if bitrate_display else "MP3"

        return render_template(
            "psp_download_final.html",
            title=title,
            filename=filename,
            file_size=file_size,
            format_display=format_display,
            video_id=video_id,
        )

    except Exception as e:
        return render_template("error.html", message=f"Download error: {str(e)}"), 500


@app.route("/download_file/<video_id>")
def download_file(video_id):
    """Serve the downloaded audio file for download"""
    try:
        song_details = get_song_details(video_id)

        title, artists = resolve_title_and_artists(video_id, song_details)
        filename = make_filename(title, artists)
        audio_path = CACHE_DIR / filename

        if not audio_path.exists():
            # Fallback to video_id filename
            audio_path = CACHE_DIR / f"{video_id}.mp3"
            if not audio_path.exists():
                return "File not found", 404

        return send_file(
            audio_path,
            as_attachment=True,
            download_name=filename,
            mimetype="audio/mpeg",
        )

    except Exception as e:
        return render_template("error.html", message=f"Error: {str(e)}"), 500


if __name__ == "__main__":
    import socket

    host = socket.gethostbyname(socket.gethostname())
    port = int(_cfg_get("port", 2001))
    print(f"PSP Music Player starting...")
    print(f"Access via: http://{host}:{port}")
    print(f"Audio cache: {CACHE_DIR}")

    # Initial cleanup
    cleanup_old_files()

    app.run(host="0.0.0.0", port=port, debug=False)
