---
name: surge-cli
description: Control and troubleshoot the Surge proxy app through surge-cli — the native binary when present, otherwise a bundled pure-Python Controller client (Linux, iSH/Minis on iOS, machines without Surge.app). Use whenever a task involves Surge in any way — checking or changing its state (outbound mode, policy groups, profiles, modules, features), diagnosing network problems on a machine running Surge (DNS, routing decisions, proxy connectivity, Tailscale/WireGuard tunnels, gateway-mode clients), reading Surge logs, inspecting requests and traffic, running an HTTP capture and reading captured request/response headers and bodies (also from a remote iPhone), building and verifying jq/script rewrites, adding temporary rules, running scripts, measuring performance, or writing and packaging a Surge plugin. Prefer surge-cli over GUI instructions or profile file edits for any Surge operation that the CLI can perform.
---

# Surge CLI Operations

`surge-cli` is a full-featured control and diagnostics interface for Surge. It
can answer most questions about a running Surge instance directly — prefer
asking the CLI over guessing, reading profile files, or telling the user to
click through the GUI.

> Synced from the Surge-bundled skill (see `references/upstream-SKILL.md`);
> the Backends, Remote Instances and HTTP Capture & Rewrite sections, and the
> tailnet note in Diagnostics Workflow, are local additions.

## Backends

Always invoke `<skill-dir>/scripts/surge-cli` (on this Mac:
`~/.claude/skills/surge-cli/scripts/surge-cli`). It dispatches to:

1. **native** — `surge-cli` on `PATH`, else
   `/Applications/Surge.app/Contents/Applications/surge-cli`;
2. **python** — `scripts/surge_cli.py` (Python 3 stdlib only) when no native
   binary exists.

Run `scripts/surge-cli --which-backend` once per session; force one with
`SURGE_CLI_BACKEND=native|python`. Rules that depend on the backend:

| | native | python |
|---|---|---|
| Output | default rendered output; `--raw` only for missing fields | **always `--raw`** |
| Target | local Surge, or `--remote` | always a Controller: `-r`, else `$SURGE_CLI_REMOTE`, else `127.0.0.1:6170` |
| `--check`, `lsp`, `plugin validate\|pack` | available | unavailable (exit 2) — say so; do not emulate |
| `-h`, `help <command>` | authoritative | abridged; use the Command Reference |
| `retrieve-data` (captured bodies) | broken (`Socket closed by remote peer`) | works; decodes gzip/zstd — the dispatcher routes it here automatically unless `SURGE_CLI_BACKEND` is set |

Protocol details and limits: [Python Backend](references/python-backend.md).

## Connecting

1. Use the default rendered output on the native backend — it is the supported
   interface for agents. Pass `--raw` only when a documented field is missing
   from the rendered form. On the python backend always pass `--raw`.
2. For a remote instance add `--remote host:port` (IPv6: `[addr]:port`).
   Supply the password via `--password-stdin`, `SURGE_CLI_PASSWORD`, or the
   terminal prompt — never in argv.
3. The native CLI is self-documenting: `surge-cli -h` shows the command groups
   and `surge-cli help <command>` (for example `help rule match`, `help dump`)
   shows detailed usage. Use it when unsure about syntax before falling back
   to the reference file.
4. `surge-cli --check <path>` validates a profile file without a running Surge.
   For editor integration, `surge-cli lsp` provides offline stdio diagnostics;
   unknown `[General]` keys are reported as warnings. It is a persistent LSP
   server, not a one-shot validation command. Both are native-only.

## Remote Instances

Remote target = the other Surge's External Controller port (for example an
iPhone reachable over Tailscale).

1. The password lives in `<skill-dir>/.env` (`SURGE_CLI_PASSWORD=...`, mode
   600), created by the user from `.env.example` (see INSTALL.md); if it is
   missing, ask the user to create it rather than asking for the password in
   chat. Load it and feed it via stdin so the secret stays out of argv and shell
   history:

   ```bash
   set -a; . ~/.claude/skills/surge-cli/.env; set +a
   printf '%s\n' "$SURGE_CLI_PASSWORD" | ~/.claude/skills/surge-cli/scripts/surge-cli --password-stdin -r <host>:<port> status
   ```

   Never print `.env` or the password, never copy it into other files, and ask
   the user to rotate it if it was pasted in chat.
2. The port is the target's `external-controller-access` port from its
   profile; the target must listen on a reachable address (not only
   127.0.0.1).
3. Address choice: on the same LAN use the device's mDNS name
   (`<device-name>.local:<port>`; breaks when the network or device name
   changes); otherwise the Tailscale MagicDNS name
   (`<host>.<tailnet>.ts.net:<port>`, Tailscale on both ends). Check resolution
   first with `ping -c1 -t3 <name>`.
4. Connectivity smoke test, read-only: `version`, `status`, `dump summary`.
5. Remote reads are safe by default; confirm with the user before any `set`,
   `reload`, `restart-engine`, `switch-profile`, or `stop` on a remote device.
6. On an iPhone reached through Surge's own Tailscale, `reload` and
   `feature set capture …` often report "timed out" or `Socket closed by
   remote peer` because the change resets
   the controller connection — the change usually did apply. Always re-read
   the state (`feature get`, `show-policy`, `status`) instead of retrying.
7. A phone with no `DEVICE:` entry in the local `dump profile` is not a Ponte
   device; use `--remote`, not `test-ponte`.
8. To verify both backends agree on a target: `scripts/parity_check.sh
   <host:port>` (read-only; needs the native binary locally).

## Maintenance

`scripts/sync_upstream.sh [ssh-host]` refreshes the official files
(`references/upstream-SKILL.md`, command reference, plugin guide, agent
metadata, icon) from Surge.app and never touches this file or `scripts/`.
When `upstream-SKILL.md` changes, merge its new guidance here by hand.

## Picking the Right Command

Match the question to the command family; full semantics are in the
[Command Reference](references/command-reference.md).

| Question / task | Commands |
|---|---|
| What is Surge's current state? | `status`, `version`, `environment` |
| Is the network itself healthy? | `dump summary` (passive snapshot; run it first), then `test v4-router\|dns\|encrypted-dns\|external-ip\|nat-type` for active probes |
| How would Surge route this request? | `rule match <host\|url>`; use `rule explain` when the question is "why" — it walks every policy-group hop with its decision reason |
| Is this proxy/policy working? | `test-policy`, `test-policy-udp`, `test-group`, `test-policy-bandwidth`; `http probe <url> [policy]` for a real end-to-end request |
| What is wrong with a Tailscale/WireGuard tunnel? | `proxy-runtime-status "<policy-name>"` (name from `dump policy`; a line-hash also works) — it exposes handshakes, DERP, Exit Node, and peer paths that nothing else shows |
| What is Surge resolving this to? | `dns lookup <domain>`, `dns trace` for the resolver log, `geoip <ip>` for GEOIP/IP-ASN database checks, `flush dns` |
| What happened just now? | `log memory 500` (all levels, recent), `log file 1000` (longer history), `log watch` (follow live), `logbook`, `script-log` |
| What connections/traffic exist? | `dump active\|recent\|request\|traffic\|traffic-stat\|traffic-stat-host`, `watch request`, `watch speed`, `kill <id>` |
| What did this app send/receive? Does my rewrite work? | `feature set capture on\|off`, `dump recent` (`replica` records with headers), `retrieve-data <id> request\|response` — see [Capture Workflow](references/capture-workflow.md) |
| Change routing behavior now | `mode set`, `global-policy set`, `policy-group set`, `rule temp add`, `set` |
| Manage configuration | `profile list\|current\|diff\|check\|switch`, `module enable\|disable`, `feature set`, `managed-profile update`, `external-resource update`, `reload` |
| Gateway-mode client problems (macOS) | `device list\|show`, `vmnet status\|arp\|ndp\|ra`, `reconnect-device` |
| Memory / performance concerns | `dump performance`, `dump rule-usage`, `benchmark rule-matching`, `benchmark encryption` |
| Run or debug scripts | `script list\|run\|evaluate` |
| Plugins | `plugin ...` — see [Plugin Authoring Guide](references/plugin-authoring.md) |

## Daily Management

Task-oriented commands cover routine operations — use them instead of raw
`set` key-paths whenever one exists, because they validate input and return
the resulting state rather than a bare success:

```bash
surge-cli mode set rule                      # rule | direct | proxy
surge-cli policy-group set "Proxy" "HK"      # select-group choice
surge-cli policy-group set "Auto" auto       # clear an auto-group override
surge-cli feature set mitm on                # mitm, rewrite, scripting, capture,
                                             # packet-capture, cellular-mode
                                             # (+ system-proxy, enhanced-mode on macOS)
surge-cli profile switch "Home.conf"
surge-cli module enable "Module A" "Module B"
```

`feature set system-proxy` / `enhanced-mode` wait for the actual state
transition and fail if it does not complete. An invalid `profile check` sets a
non-zero exit status, which makes it usable in automation.

## Mutating State Safely

- Collect context before changing anything: `environment`, `dump policy`,
  `dump profile` as relevant. Re-run the same read command afterwards to
  verify the effect.
- For raw environment updates, `set` accepts multiple `key=value` pairs in one
  command; use minimal key-path deltas. `<nil>` and `(null)` assign null.
  Key definitions are in section 4 of the [Command Reference](references/command-reference.md).
- For debugging sessions, prefer **temporary rules** over profile edits: they
  take effect immediately, precede all profile rules, and vanish when Surge
  stops, so nothing needs cleanup.

```bash
surge-cli rule temp add "DOMAIN-SUFFIX,example.com,Proxy"
surge-cli rule temp list
surge-cli rule temp flush
```

## Diagnostics Workflow

Start passive, then narrow down; do not jump straight to broad log searches.

1. `status` and `dump summary` — profile, mode, warnings, interfaces, DNS.
2. Reproduce the routing decision offline with `rule match` / `rule explain`,
   and verify its inputs with `dns lookup` / `geoip` when a rule depends on
   resolution or IP databases.
3. Test the selected policy (`test-policy`, `http probe`).
4. For per-proxy internals — especially Tailscale and WireGuard —
   `proxy-runtime-status` is the primary tool; collect it before log analysis.
5. Only then use `log memory` / `log watch` for details, or `diagnostics` for
   the streaming self-check.

For gateway-mode (macOS) client connectivity, inspect the virtual interface
directly: `vmnet arp` / `vmnet ndp` for neighbor resolution, `vmnet ra` for
IPv6 RA takeover state, and `device show <mac>` for the client's records.

**Proxy whose server is a tailnet address (100.64.0.0/10).** A proxy policy's
own connection to its server does not go through the rule set, so it does
**not** use Surge's built-in Tailscale policy even though `rule match <100.x>`
shows `Tailscale… (internal)`. It only works where something else routes
100.x (e.g. a home router running Tailscale) and fails on cellular with
"timeout (proxy handshake)". Fix: add `underlying-proxy=<Tailscale policy>` to
that proxy line. Confirm by capturing on the server (`tcpdump port <port>`):
before the fix no packets from the client arrive; after it they arrive on
`tailscale0` from the client's tailnet IP. Traffic inside the tunnel is
WireGuard-encrypted, so carrier "zero-rating" based on HTTP obfs host no
longer applies.

## HTTP Capture & Rewrite

Use this to answer "what exactly does this app send/receive" and to build and
verify jq/script rewrites. Full procedure: [Capture Workflow](references/capture-workflow.md).

- Turning capture on/off is a state change: confirm first, record the starting
  state, always restore it. Data stays readable after `capture off`.
- Find records with `dump recent` (`replica: true`); headers are in
  `requestHeader` / `responseHeader`; bodies via `retrieve-data` (Python
  backend, auto-routed by the dispatcher; gzip/zstd decoded).
- A capture contains every app's traffic: read only the relevant records,
  never print credentials, and clean up extracted bodies.
- Rewrites go into a module, are validated (`--check`, `script evaluate`),
  applied with consent, then proven by a second capture (`modified: true` and
  the changed body).

## Streaming Commands

`test-policy-bandwidth`, `benchmark encryption`, `test-ponte`, `diagnostics`,
`log watch`, and `watch ...` stream output: process incremental chunks,
respect completion markers (`hasMore=false` or a command-specific completion
payload), and never assume a single response frame. A subscribed `watch` may
stay idle indefinitely; other stages time out after 60 seconds without
progress.

## Platform and Version Gates

- macOS-only: `profile list|check`, all `device` operations, `vmnet`,
  `set-dhcp-device`, `managed-profile`, `update-profile`, `plugin` (online
  subcommands), `unattended-upgrade`.
- Newer commands require a matching Controller protocol version on the Surge
  side (`rule`/`dns`/`http probe`/`security ban` ≥20; `geoip`,
  `dump performance|rule-usage|virtual-ip`, `benchmark rule-matching` ≥22;
  `vmnet` ≥23; `plugin` ≥24). An older core answers `Unknown command`; check
  `surge-cli version` when targeting a remote or outdated instance.

## Plugin Development

To write, test, or package a Surge plugin (JavaScript extensions; currently
the `ap-controller` type), follow the
[Plugin Authoring Guide](references/plugin-authoring.md). The development loop
is `plugin load-unpacked` → `plugin parameters` → `plugin configure` (runs the
plugin's own validation) → check the device panel; `plugin validate` and
`plugin pack` work offline without a running Surge.

## Reference

- [Command Reference](references/command-reference.md) — full command catalog,
  subcommand semantics, environment key definitions, response envelope.
- [Plugin Authoring Guide](references/plugin-authoring.md) — package layout,
  manifest schema, JavaScript API, testing, distribution.
- [Python Backend](references/python-backend.md) — Controller protocol,
  differences from the native binary, `retrieve-data` wire format, parity check.
- [Capture Workflow](references/capture-workflow.md) — HTTP capture, record
  fields, reading bodies, privacy rules, rewrite build-and-verify loop.
