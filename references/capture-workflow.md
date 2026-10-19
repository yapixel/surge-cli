# HTTP Capture & Rewrite Workflow

Local addition, verified against Surge Mac 6.x and Surge iOS 5.102 (Controller
protocol 26). `<cli>` = `<skill-dir>/scripts/surge-cli`; for a remote target add
`--password-stdin -r <host:port>` as in SKILL.md → Remote Instances.

## 1. Capture

```bash
<cli> feature get capture          # record the starting state
<cli> feature set capture on       # confirm with the user first — it is a state change
#   ... user reproduces the traffic (or run curl on the Mac) ...
<cli> feature set capture off      # always restore; on a remote iPhone this may report a
<cli> feature get capture          # timeout or "Socket closed" although it succeeded — re-check
```

- Capture applies MitM to every hostname except the profile's exclusions
  (`ReplicaSessionParameters.mitmOverrideHostnames` in `environment`), so HTTPS
  bodies are visible unless the app pins certificates (the connection then fails).
- Records and bodies survive `capture off` until the next capture session starts,
  so turn capture off first and analyse afterwards.

## 2. Find the records

`<cli> --raw dump recent` (`requests[]`). Fields that matter:

| Field | Meaning |
|---|---|
| `replica: true` | recorded by the capture session (only these have bodies) |
| `id` | record id for `retrieve-data` |
| `URL`, `method`, `status`, `rule`, `policyName`, `processPath` | what and how it was routed |
| `requestHeader`, `responseHeader` | raw header blocks (HTTP records only, capture on) |
| `streamHasRequestBody`, `streamHasResponseBody` | whether a body exists |
| `modified` | `true` when a rewrite/script changed the message — use it to verify rewrites |
| `replicaDirectoryPath` | Mac only: on-disk copy of the record |

Filter by host or a unique query token instead of reading every record.
`dump recent` is a rolling window (about 50 records on iOS, 200 on macOS), so
note the relevant ids right after the capture: once they scroll out of the
window, `retrieve-data <id>` still works but the record (headers) is gone.

## 3. Read bodies

```bash
printf '%s\n' "$SURGE_CLI_PASSWORD" | <cli> --raw --password-stdin -r <host:port> \
  retrieve-data <id> response > body.bin     # or: request
```

- Works over the Controller on the **Python backend only** (the dispatcher routes
  `retrieve-data` there automatically; the native client fails with
  `Socket closed by remote peer`). Verified on iOS; wire format in
  [Python Backend](python-backend.md).
- gzip and zstd bodies are decoded (stderr names the decoding); br/deflate are
  written as-is — check `Content-Encoding` in `responseHeader`.
- `Data does not exist` (exit 1): no body for that id/part, or a new capture
  session cleared it.
- On the Mac the same data is also on disk under `replicaDirectoryPath`
  (`$TMPDIR/Surge Capture/<session>/Requests/<id> - …/`): `model.json` (the
  record), `request.dump`, `response.dump` (bodies as received).

## 4. Privacy rules

- A capture records **every app** on the device, including tokens, cookies and
  account data. Read only the records relevant to the task; never print
  `Authorization`, `Cookie`, `Set-Cookie` values or credentials found in bodies.
- Keep extracted bodies in the scratchpad, delete them when done, and offer to
  move the Mac `Surge Capture/<session>` directory to the Trash (ask first).

## 5. Rewrite

Write the change, validate it, apply it, then capture again to prove it.

1. **Choose the mechanism** (syntax: use the surge-kb skill):
   - JSON field edits → `http-response-jq <url-regex> '<jq filter>'`
     (`[Body Rewrite]` style); test the filter locally with `jq` against the
     captured body first.
   - Logic, non-JSON bodies, header changes → `[Script]` with
     `type=http-response` (or `http-request`), `requires-body=1`.
2. **Put it in a module**, not the main profile, so it can be disabled or
   removed in one step; MitM must cover the hostname.
3. **Validate**: `<cli> --check <profile>` (native only) or `profile check <name>`.
   Dry-run scripts with `<cli> script evaluate <file.js> http-response [timeout]`.
   The mock is a **fixed sample** (verified): `$request` = `{method, url:
   "http://www.apple.com/"}`, `$response` = `{status: 200, headers, body:
   '{"foo":"bar"}'}`; `http-request` mode gives `$request.body = null`. To test
   against a real captured body, pass it as the argument and read it first:

   ```js
   const body = (typeof $argument === "string" && $argument) ? $argument : $response.body;
   ```
   ```bash
   <cli> --raw script evaluate rewrite.js http-response 10 auto "$(cat body.json)"
   ```
   Works on both backends; only small bodies were tested — very large bodies may
   hit argv limits, so trim the sample if needed. Remove the `$argument`
   fallback (or keep it harmless) before shipping the script.
4. **Apply** (confirm with the user): `module enable "<name>"` or `reload`.
   Re-check state afterwards (remote reloads may report a timeout).
5. **Verify**: capture again, reproduce, then compare the new body from
   `retrieve-data` with the original and confirm `modified: true`.
