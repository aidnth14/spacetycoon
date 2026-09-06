# Changelog

## Server hardening
- Per-IP and global connection caps, connection-rate throttling, per-message
  rate limiting, 2KB message size cap.
- Room codes lengthened 4→6 chars; failed-join lockout to stop brute-forcing.
- Stale unjoined rooms now auto-expire instead of leaking memory.
- See `SECURITY.md` for the full breakdown.

## Settings panel + gamepad support
- Gear icon next to HOST opens a settings modal: music volume slider, mute
  toggle.
- Gamepad navigation: D-pad/stick to move focus, A to confirm, B to back
  out — falls back to mouse/keyboard automatically, hot-pluggable.

## Music playlist
- Added a 4-track looping playlist (Neon Market, Orbital Drift, Cargo Run,
  Boardroom), crossfading between tracks via `MUSIC_END_EVENT`.
- The first four tracks are original, synthesized from scratch in pure
  Python (`assets/_gen_music.py`) — chord-progression pads, plucks, and
  bells at a correct 44100Hz.
- Added three 8-bit chiptune tracks (Sanctuary Guardians, Alien Wolves,
  Melancholic Walk), kept as their original unmodified WAV files.

## UI redesign
- Replaced the flat, loosely-positioned layout with a proper card-panel
  shell: header + centered bordered card with drop shadow, consistent
  spacing, glowing gold title text, pulsing room-code display.
- Added friendly, human-readable connection errors (`network.py`
  `humanize_connect_error`) instead of raw Python exceptions.
- Made `Connection.connect()` and `.close()` fully non-blocking (moved off
  the main thread) — previously a slow/hanging connect or close could
  freeze the whole UI during a state transition.

## Initial build
- Room-code relay server (WebSocket) deployed on Fly.io.
- pygame client with Host/Join flow and live ping/pong RTT display.
- Public-DNS (8.8.8.8) fallback resolver for stale local DNS caches.
