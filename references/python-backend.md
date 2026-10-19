# Python Controller Backend

`scripts/surge_cli.py` is a pure-Python (stdlib only, Python 3.8+) client for the
Surge External Controller. `scripts/surge-cli` runs it automatically when no
native `surge-cli` binary exists (Linux, iSH/Minis on iOS, macOS without
Surge.app). Force a backend with `SURGE_CLI_BACKEND=native|python`; check the
resolved one with `scripts/surge-cli --which-backend`.

## Protocol

The same transport the native `surge-cli --remote` uses — CRLF-delimited JSON
Lines over plain TCP:

1. Client sends the password + CRLF.
2. Server replies `{"result":"Welcome to Surge CLI"}` (or an `error`).
3. Client sends `{"argv":[...]}` + CRLF.
4. Server returns one result object, or a stream of objects for streaming
   commands (finite streams end with `hasMore=false`).

The Controller parses most argv itself, so new ordinary commands work without
client changes. The client reproduces the native CLI's local conversions:
`summary`, `profile diff`, `rule temp *`, `watch speed`, and
`script evaluate <file>` (Base64 + mock-type name → numeric id).

## Differences from the native binary

| Area | Native | Python backend |
|---|---|---|
| Target | local Surge without `--remote` | always a Controller address: `-r`, else `$SURGE_CLI_REMOTE`, else `127.0.0.1:6170` |
| Output | rendered text is the supported interface | **always pass `--raw`**; renderers cover only common commands |
| Client-side validation | rejects unknown commands unless `--raw` | none; everything is passed through |
| Offline commands | `--check`, `lsp`, `plugin validate`, `plugin pack` | refused with exit 2 |
| Stage timeout | 60 s without progress | 60 s (subscriptions such as `watch` wait indefinitely) |

## Captured bodies: `retrieve-data`

`retrieve-data <record-id> <request|response>` returns a captured body. Ids come
from `dump recent` records with `replica: true` (HTTP capture was on). The
native client cannot parse this reply and fails with `Socket closed by remote
peer`, so `scripts/surge-cli` routes `retrieve-data` to the Python backend
automatically (an explicit `SURGE_CLI_BACKEND` still wins):

```sh
printf '%s\n' "$SURGE_CLI_PASSWORD" | scripts/surge-cli \
  --raw --password-stdin -r <host:port> retrieve-data <id> response > body.bin
```

Wire format (verified against Surge iOS, protocol 26): success is one frame,
`<uint64 little-endian length> CRLF <body bytes>`, after which the server closes
the connection; failure is a normal JSON line such as
`{"error":"Data does not exist"}` (exit 1). The body keeps its HTTP
`Content-Encoding`; the client undoes gzip and zstd by magic bytes (zstd needs
Python 3.14+ or the `zstd` CLI) and notes the decoding on stderr. Other
encodings (br, deflate) are written as-is — check `responseHeader` in the
record. Bodies are written to stdout as bytes.

Records and bodies survive turning capture off until the next capture session.

`plugin load-unpacked <dir>` is passed through: the directory path is resolved
on the Surge host, not on the machine running the client.

## Security

The password and all traffic are unencrypted TCP, exactly as with the native
client. Use it only over localhost, a trusted LAN, or an encrypted overlay such
as Tailscale. Credentials come only from `--password-stdin`,
`SURGE_CLI_PASSWORD`, or a no-echo prompt — never argv, never files written by
the client.

## Verifying parity

```sh
SURGE_CLI_PASSWORD=... scripts/parity_check.sh <host:port>
```

Runs read-only commands through both backends against the same Controller and
reports `identical`, `same-shape` (live values differ), or `DIFF`. Requires the
native binary on the machine running the check.
