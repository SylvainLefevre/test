# xtream-filter

Fetches the live/VOD/series catalog from an existing Xtream Codes source,
filters it by category and language, and republishes the filtered result as
a new local API that speaks the same Xtream Codes protocol — so any
existing IPTV player (TiviMate, IPTV Smarters, etc.) can point at it exactly
like it would point at a normal provider.

Written in plain Python 3.9+ (standard library + PyYAML only) so it can be
deployed on a Raspberry Pi 3 using nothing but `apt` — no compiler, no pip,
no virtualenv, no cross-compilation.

## How it works

1. On startup, and then every `refresh.interval_minutes`, xtream-filter logs
   into your upstream Xtream source and fetches all live/VOD/series
   categories and streams.
2. Each category is checked against your `filters` (category name
   include/exclude list, and/or language regex patterns matched against the
   category name). Streams/movies/series inherit their category's verdict.
3. The filtered snapshot is kept in memory and served over HTTP, using the
   same endpoints a real Xtream panel exposes:
   - `GET /player_api.php?username=...&password=...&action=...`
   - `GET /live/<user>/<pass>/<id>.<ext>`
   - `GET /movie/<user>/<pass>/<id>.<ext>`
   - `GET /series/<user>/<pass>/<id>.<ext>`
   - `GET /xmltv.php?username=...&password=...`
4. Your IPTV player is configured with the Pi's address and the **local**
   `server.username`/`server.password` from `config.yaml` — never your real
   provider credentials.
5. Playback requests are, by default, answered with an HTTP redirect to the
   real source URL (`streaming.mode: redirect`), so video traffic never
   flows through the Pi. Set `streaming.mode: proxy` if you need the Pi to
   relay the bytes itself (heavier, only recommended for a couple of
   simultaneous streams on a Pi 3).

## Project layout

```
xtream_filter/
  config.py          load/validate config.yaml
  xtream_client.py    HTTP client for the upstream Xtream source
  filters.py          category/language filtering engine
  store.py            in-memory snapshot + periodic background refresh
  server.py           the republished Xtream-compatible HTTP API
  __main__.py          entry point (python3 -m xtream_filter)
tests/                 unit tests (stdlib unittest, no extra dependencies)
deploy/                systemd unit + install/CD scripts for the Pi
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and edit it. See the comments
in that file for every option: source credentials, local credentials,
refresh interval, streaming mode, language regex definitions, and the
per-section (live/vod/series) category and language filters.

Filter modes for both `categories` and `languages`:
- `all`: no filtering.
- `include`: only items matching the list pass.
- `exclude`: everything passes except items matching the list.

Category matching is a case-insensitive substring match against the
category name. Language matching is done by running the regex patterns you
declare under top-level `languages:` against the category name.

## Run it locally

Requires Python 3.9+ and PyYAML (`pip install pyyaml`, or `apt install
python3-yaml` on Debian/Ubuntu).

```sh
python3 -m xtream_filter --config config.yaml
```

Run the tests:

```sh
python3 -m unittest discover -s tests -v
```

## Deploy to a Raspberry Pi 3

```sh
scp -r . pi@raspberrypi.local:~/xtream-filter
ssh pi@raspberrypi.local
cd ~/xtream-filter
./deploy/install.sh
```

`deploy/install.sh` installs `python3`/`python3-yaml` via `apt`, creates a
dedicated `xtream-filter` system user, copies the `xtream_filter/` package
and a starter `config.yaml` to `/opt/xtream-filter`, and registers/enables
a systemd service from `deploy/xtream-filter.service`. No build step, no
architecture to pick: the same source runs on 32-bit or 64-bit Raspberry
Pi OS unchanged.

After installing:

```sh
sudo nano /opt/xtream-filter/config.yaml   # set source creds + filters
sudo systemctl start xtream-filter
journalctl -u xtream-filter -f
curl http://localhost:8081/healthz
```

Point your IPTV player at `http://<raspberry-pi-ip>:8081` with the
`server.username` / `server.password` you set in `config.yaml`.

## Continuous deployment

Once the Pi has xtream-filter installed via `deploy/install.sh` above, you
can wire up automatic deployment on every merge to `main`:

1. **Register a self-hosted GitHub Actions runner on the Pi.** In the repo
   on GitHub: *Settings → Actions → Runners → New self-hosted runner*,
   choose Linux + ARM (32-bit Pi OS) or ARM64 (64-bit Pi OS) — this picks
   the architecture of the GitHub Actions runner agent itself, a separate
   compiled tool from GitHub, unrelated to xtream-filter being plain
   Python — and copy the `--url` and `--token` values it shows you (the
   token expires after about an hour). Then, on the Pi:

   ```sh
   cd ~/xtream-filter
   ./deploy/setup-runner.sh "https://github.com/<owner>/<repo>" "<token>"
   ```

   This creates a dedicated `github-runner` system user, installs the
   runner as its own systemd service labeled `raspberry-pi`, and installs a
   narrowly-scoped sudoers rule so that user can run exactly one thing as
   root: `/opt/xtream-filter/deploy.sh <checked-out-repo-path>`, which
   copies the updated `xtream_filter/` package into place and restarts the
   `xtream-filter` service — nothing else.

2. **That's it.** `.github/workflows/deploy.yml` triggers on every push to
   `main`: your Pi's self-hosted runner (matched via the `raspberry-pi`
   label) checks out the repo directly, installs the updated code, restarts
   the service, and verifies `/healthz` responds before finishing the run.
   There is no compile/cross-compile step to run first, since Python is
   interpreted and architecture-independent.

Because the runner is self-hosted, it makes an outbound connection to
GitHub to pick up jobs — no inbound port forwarding or public IP is needed
for deployment itself, even though the workflow assumes the rest of
`deploy/install.sh` has already been run once by hand.

`.github/workflows/ci.yml` additionally runs a syntax check and the unit
test suite on every pull request and push to `main`, using Python 3.9 —
the same version `apt` provides on Raspberry Pi OS Bullseye — independent
of deployment.

## Known limitations

- **Series episode playback is not individually filtered.** Series are
  filtered at the catalog level (a hidden series never appears in
  `get_series`), but the per-episode ids used by `/series/.../<episode_id>`
  come from `get_series_info`, a different id space that is not
  pre-enumerated on every refresh (doing so would mean one extra upstream
  request per kept series on every refresh cycle, which does not scale well
  from a Raspberry Pi 3 against large catalogs). Anyone who already has a
  direct episode id/URL from an unfiltered source could still stream it.
  If you need hard per-episode enforcement, this is the first place to
  extend the `store` module.
- `get_series_info`, `get_vod_info`, `get_short_epg` and similar detail
  actions are proxied straight to the upstream source once the id they
  target passes an allow-list check; the EPG itself (`xmltv.php`) is not
  filtered to match the trimmed live channel list — it is passed through
  as-is (redirected or proxied depending on `streaming.mode`).
- No TLS/HTTPS termination is included; run this behind a reverse proxy
  (e.g. Caddy, nginx) or a VPN (Tailscale, WireGuard) if you need to reach
  it from outside your home network.
- The bundled HTTP server (Python's `http.server.ThreadingHTTPServer`) is
  fine for a handful of concurrent IPTV player connections on a Pi 3, but
  is not tuned for heavy concurrent load.
