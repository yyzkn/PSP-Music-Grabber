# PSP Music Grabber

PSP Music Grabber is a lightweight web tool to search and download audio from YouTube (using [ytmusicapi](https://github.com/sigma67/ytmusicapi) + [yt-dlp](https://github.com/yt-dlp/yt-dlp)), write PSP-compatible ID3 metadata, and serve a simple PSP-friendly web UI. Tested on my JP-Region 2001 PSP Model's and my very own crappy server.

## Project goals

- Make it easy for PSP users to obtain MP3 files with compatible ID3 metadata and cover art.
- Provide a minimal web interface to search, and download audio from YouTube.

## Key features

- Search songs using YT Music API
- Stream audio for modern browsers (for testing audio data)
- Download MP3 with PSP-optimized ID3 metadata like title, artist, album, year and cover images

## Requirements

- Python 3.10+
- ffmpeg (must be in PATH or set via `ffmpeg_location` in `config.json`)
- Python packages: see `requirements.txt`
- Node.js (optional, only to avoid some yt-dlp JS warnings)

## Quick installation

```bash
git clone https://github.com/yyzkn/PSP-Music-Grabber
cd PSP-Music-Grabber
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

## Accessing the page

Once the server is running, open your web browser and go to:

    	http://<server-ip>:<port>/

For example, if running locally with the default config:

    	http://127.0.0.1:2001/

### How to check your server IP address

- **On Linux:**

  - Open a terminal and run:
    ```bash
    hostname -I
    ```
    or
    ```bash
    ip addr show
    ```
  - Look for your local network IP (e.g. 192.168.x.x or 10.x.x.x).

- **On Windows:**
  - Open Command Prompt and run:
    ```cmd
    ipconfig
    ```
  - Look for the "IPv4 Address" under your active network adapter.

To access from your PSP:

- Connect your PSP to the same Wi-Fi network as your server.
- Open the PSP web browser.
- Enter your server's IP address and port (e.g. `http://192.168.1.100:2001/`).

You should see the PSP Music Grabber interface.

notes: if the page still didn't load, make sure to disable LAN-to-LAN isolation from your router setting.

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
