# PSP Music Grabber

PSP Music Grabber is a lightweight web tool to search and download audio from YouTube (using [ytmusicapi](https://github.com/sigma67/ytmusicapi) + [yt-dlp](https://github.com/yt-dlp/yt-dlp)), write PSP-compatible ID3 metadata, and serve a simple PSP-friendly web UI. tested on my own crappy server and 2001 PSP (JP-Region) Model's.

## Project goals

- Make it easy for PSP users to obtain MP3 files with compatible ID3 metadata cover art.
- Provide a minimal web interface to search, and download audio from YouTube.

## Key features

- Search songs using YT Music API
- Stream audio for modern browsers (for testing audio data)
- Download MP3 with PSP-optimized ID3 metadata like title, artist, album, year and cover images

## Requirements

- Python 3.10+
- ffmpeg (must be in PATH or set via `FFMPEG_LOCATION`)
- Python packages: see `requirements.txt`
- Node.js (optional, only to avoid some yt-dlp JS warnings)

## Quick installation

```bash
git clone <repo-url> psp-music-grabber
cd psp-music-grabber
python -m venv .venv
source .venv/bin/activate    # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Make sure `ffmpeg` is available (`ffmpeg --version`). If ffmpeg is not in your PATH, configure `ffmpeg_location` in `config.json`.

## Configuration

You can configure the app with environment variables or a `config.json` file placed next to `app.py` (if there's no `config.json`, create it). Environment variables override `config.json` values.

Example `config.example.json`:

```json
{
	"port": 2001,
	"ffmpeg_location": "/usr/bin/ffmpeg",
	"cache_dir": "./audio_cache"
}
```

## Running the app

Quick Run:

```bash
source .venv/bin/activate
python app.py
```

Deploy it!:

Gunicorn (Linux):

```bash
pip install gunicorn
gunicorn -w 3 -b 127.0.0.1:2001 app:app
```

Waitress (Windows):

```powershell
pip install waitress
waitress-serve --listen=127.0.0.1:2001 app:app
```

## Running as a service (systemd example)

Example systemd unit:

```
[Unit]
Description=PSP Music Grabber
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/psp-music-grabber
Environment=PATH=/path/to/psp-music-grabber/.venv/bin
ExecStart=/path/to/psp-music-grabber/.venv/bin/gunicorn -w 3 -b 127.0.0.1:2001 app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

For Windows, use NSSM or a service wrapper to run `waitress-serve` as a service.

## Important notes

- `yt-dlp` might warn about missing JavaScript runtime; installing Node.js removes this warning and enables more complete extraction.
- `ffmpeg` is a system dependency and is not installed via `pip`. for Windows, you can download ffmpeg.exe and save it anywhere.
- Audio files are stored temporarily in `CACHE_DIR` and are automatically cleaned up after ~10 minutes.

## Contributing

Contributions are welcome. Please open issues or pull requests.

## License

This project is available under the MIT License. See the `LICENSE` file for details.

## Credits

[sigma67](https://github.com/sigma67)
[yt-dlp](https://github.com/yt-dlp)
