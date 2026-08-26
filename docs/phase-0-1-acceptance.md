# Phase 0/1 iPhone acceptance

Record date, iOS version, LAN IP, and results. Do not begin Phase 2 until every row passes.

## Phase 0

- [ ] Trust `certs/lan.crt` on iPhone and open the PWA over HTTPS.
- [ ] Add the PWA to the Home Screen and launch it in landscape.
- [ ] Confirm the status changes from 接続中 to 待機中.
- [ ] Stop/restart the PC server; confirm the PWA returns to 待機中 without a tap.
- [ ] Disable/enable iPhone Wi-Fi; confirm automatic recovery without a tap.

## Phase 1

- [ ] Tap マイクを有効にする once after PWA launch.
- [ ] In a quiet room, try 20 double claps. Successes: ____ / 20 (pass: at least 18).
- [ ] Leave it for one hour under normal room noise. False wakes: ____ (pass: at most 1).
- [ ] Open 検出ログ and tune ratio/HF/gap only from recorded candidate data if needed.
- [ ] Enable Guided Access and leave the PWA visible overnight while charging.
- [ ] Confirm framing is stable and the display remains usable in the morning.
