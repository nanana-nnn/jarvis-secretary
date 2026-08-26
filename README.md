# JARVIS Secretary — Phase 0/1

HTTPS/WSS connection, installable iPhone PWA, finite-state UI, and local double-clap detection. Audio upload, speech recognition, Vault access, and agents are intentionally not implemented.

## Setup

```fish
cp .env.example .env
# Replace 192.168.0.x with this PC's LAN address in .env
./scripts/gen-cert.sh (string split = (grep '^HOST=' .env))[2]
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm install
```

## Run

In two terminals:

```fish
.venv/bin/python -m server
npm run dev
```

Open `https://<HOST>:5173` on the iPhone, trust the generated certificate, then tap **マイクを有効にする** once. Add the page to the Home Screen for standalone landscape use.

## Verify

```fish
.venv/bin/pytest
npm test
npm run build
```

The Phase 0 restart/Wi-Fi recovery test and Phase 1 clap accuracy/overnight test require the target iPhone and room, so use `docs/phase-0-1-acceptance.md`.
