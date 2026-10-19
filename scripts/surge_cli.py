#!/usr/bin/env python3
"""Pure-Python Surge External Controller client, used when the native surge-cli is unavailable.

Speaks the same CRLF-delimited JSON Lines protocol as `surge-cli --remote`;
the Controller parses argv, so ordinary commands pass through unchanged.
"""
from __future__ import annotations
import base64, difflib, getpass, gzip, json, os, shutil, signal, socket, struct, subprocess, sys
from datetime import datetime
from pathlib import Path

signal.signal(signal.SIGPIPE, signal.SIG_DFL)

DEFAULT_REMOTE = os.getenv("SURGE_CLI_REMOTE", "127.0.0.1:6170")
# Native surge-cli times out a stage after 60 s without progress.
COMMAND_TIMEOUT = 60
CONTINUOUS_COMMANDS = {("log", "watch"), ("diagnostics",)}
FINITE_STREAM_COMMANDS = {("test-policy-bandwidth",), ("benchmark", "encryption"), ("test-ponte",)}
# Commands the native binary runs locally (bundled parser / filesystem); impossible over the Controller.
NATIVE_ONLY_COMMANDS = {("lsp",), ("plugin", "validate"), ("plugin", "pack")}

MAIN_HELP = """Surge CLI (Python Controller backend)
Usage: surge-cli <command> [arguments]

Command groups:
  Status       status, summary, version
  Routing      mode, global-policy, policy-group, rule match, rule explain, rule temp
  Profile      profile, module, feature, managed-profile, external-resource
  Plugin       plugin (list, parameters, load-unpacked, configure, enable, select)
  Network      dns, geoip, http probe, test, diagnostics, flush dns
  Inspection   dump, watch, log, logbook, proxy-runtime-status
  Automation   script, script-log, benchmark
  Gateway      device, vmnet, security ban
  Control      reload, restart-engine, switch-profile, kill, stop, unattended-upgrade
  Environment  environment, set, set-log-level

Use `help <command>` for detailed usage, for example:
  help rule match
  help dump
  help test

Available parameters:
  --raw - Output raw Controller JSON (authoritative; recommended for this backend)
  --remote/-r <host:port> - Controller address. IPv6 uses [address]:port
  --password-stdin - Read the remote password from the first line of stdin
  Remote password fallback: SURGE_CLI_PASSWORD, then a secure terminal prompt

Defaults:
  Controller: $SURGE_CLI_REMOTE, else 127.0.0.1:6170

Native-only (unavailable here): --check, lsp, plugin validate, plugin pack.
"""

HELP = {
"status":"Usage: status\n\nShow the current profile and path, outbound mode, feature states, uptime, and version.",
"summary":"Usage: summary\n\nShow network configuration, DNS state, and warnings without running active tests.",
"version":"Usage: version\n\nShow Surge, Core, Controller protocol, system, and device versions.",
"mode":"Usage: mode [get | set <rule|direct|proxy>]\n\nShow or change the outbound mode.",
"global-policy":"Usage: global-policy [get | set <policy>]\n\nShow or change the global proxy policy.",
"policy-group":"Usage:\n  policy-group list\n  policy-group get <group>\n  policy-group set <group> <policy|auto>",
"rule":"Usage: rule <match|explain> <host|url> [port] [key=value ...]\n       rule temp <list | add | remove | set-policy | flush>\n\nEvaluate active rules or manage temporary rules.",
"rule temp":"Usage:\n  rule temp list\n  rule temp add <rule>\n  rule temp remove <rule>\n  rule temp set-policy <rule> <policy>\n  rule temp flush",
"profile":"Usage: profile <list | current | diff | check <name> | switch <name>>",
"module":"Usage: module <list | enable <name...> | disable <name...>>",
"feature":"Usage: feature <list | get <name> | set <name> <on|off>>\n\nFeatures: mitm, rewrite, scripting, capture, packet-capture, cellular-mode.",
"dns":"Usage:\n  dns lookup <domain> [interface=<bsd-name>]\n  dns trace <domain> [interface=<bsd-name>]",
"geoip":"Usage: geoip <ip-address>",
"http":"Usage: http probe <url> [policy]",
"test":"Network and policy tests:\n  test-network\n  test-policy <policy-name>\n  test-policy-udp <policy-name>\n  test-policy-external-ip <policy-name>\n  test-policy-nat-type <policy-name>\n  test-policy-bandwidth <download|upload> <policy-name>\n  test-all-policies\n  test-group <group-name>\n  test <v4-router|dns|encrypted-dns|external-ip|nat-type>\n  test-ponte <device-ponte-name>",
"diagnostics":"Usage: diagnostics\n\nRun streaming network diagnostics.",
"flush":"Usage: flush dns",
"dump":"Usage: dump <type> [arguments]\n\nTypes include active, recent, request, traffic, traffic-stat, rule, policy, profile, dns, event, performance, rule-usage and virtual-ip.",
"watch":"Usage: watch <request|speed>\n\nContinuously print events; press Ctrl-C to unsubscribe.",
"log":"Usage:\n  log [file|memory] [line-count]\n  log watch",
"logbook":"Usage: logbook <limit>",
"script":"Usage:\n  script list\n  script run <cron-name>\n  script evaluate <script-js-path> [mock-script-type] [timeout] [engine] [argument]",
"plugin":"Usage: plugin <list | info | parameters | load-unpacked <dir> | configure | enable | disable | select | uninstall>\n\nmacOS only; Controller protocol >= 24. `validate`/`pack` run offline and need the native surge-cli.",
"restart-engine":"Usage: restart-engine\n\nRestart the engine and reload the profile; closes all connections and clears caches and temporary rules.",
"benchmark":"Usage: benchmark <encryption [data-size-mib] | rule-matching>",
"vmnet":"Usage: vmnet <status|arp|ndp|ra>\n\nInspect the VMNET virtual interface used by Enhanced/Gateway Mode. Available on macOS only.\n\n  status  Interface configuration, addresses, MTU, and table sizes\n  arp     IPv4 neighbors learned from Gateway Mode clients\n  ndp     IPv6 neighbor table\n  ra      IPv6 Router Advertisement takeover state",
"reload":"Usage: reload",
"kill":"Usage: kill <connection-id>",
"stop":"Usage: stop\n\nShut down Surge.",
"environment":"Usage: environment",
"set":"Usage: set <key-path>=<value> [...]",
"set-log-level":"Usage: set-log-level <log-level>",
"managed-profile":"Usage: managed-profile update\n\nUpdate and reload the active managed profile.",
"external-resource":"Usage:\n  external-resource list\n  external-resource update <key|all>\n\nList or update external resources used by the active profile.",
"proxy-runtime-status":"Usage: proxy-runtime-status <policy-name | line-hash>\n\nInspect proxy runtime details, including Tailscale/WireGuard tunnel, peer, DERP, and handshake state. Use dump policy to list policy names; quote names that contain spaces.",
"script-log":"Usage: script-log <log-name> <session-id>\n\nShow one script execution log.",
"device":"Usage: device <list | show <identifier|mac>>\n\nInspect gateway-mode devices. Available on macOS only.",
"security":"Usage:\n  security ban list   List active unauthorized-access bans\n  security ban clear  Clear unauthorized-access ban state",
"switch-profile":"Usage: switch-profile <profile-name>\n\nSwitch to another profile.",
"unattended-upgrade":"Usage: unattended-upgrade\n\nPerform an unattended Surge upgrade if one is available.",
}

def die(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)

def split_hostport(value: str):
    if value.startswith("["):
        end=value.find("]")
        if end<0 or end+1>=len(value) or value[end+1] != ":": die("Invalid remote address")
        try:
            return value[1:end], int(value[end+2:])
        except ValueError:
            die("Invalid remote port")
    if ":" not in value: die("Remote address must be host:port")
    host, port=value.rsplit(":",1)
    try: return host, int(port)
    except ValueError: die("Invalid remote port")

def credential(stdin_mode: bool):
    if stdin_mode:
        value=sys.stdin.readline().rstrip("\r\n")
    else:
        value=os.getenv("SURGE_CLI_PASSWORD", "")
        if not value and sys.stdin.isatty(): value=getpass.getpass("Controller password: ")
    if not value: die("A remote controller password is required. Set SURGE_CLI_PASSWORD or use --password-stdin.")
    return value

def parse_cli(args):
    raw=False; remote=DEFAULT_REMOTE; stdin_mode=False; command=[]; i=0
    while i<len(args):
        a=args[i]
        if a=="--raw": raw=True
        elif a in ("--remote","-r"):
            i+=1
            if i>=len(args): die(f"{a} requires host:port",2)
            remote=args[i]
        elif a=="--password-stdin": stdin_mode=True
        elif a in ("--help","-h") and not command: print(MAIN_HELP); raise SystemExit
        elif a in ("--check","-c"):
            die("--check needs the native surge-cli (bundled profile parser); use `profile check <name>` for a profile known to Surge.",2)
        else: command.append(a)
        i+=1
    return raw,remote,stdin_mode,command

def normalize(argv):
    """Apply client-side argument conversions used by official surge-cli."""
    if argv==["summary"]: return ["dump","summary"]
    if argv==["profile","diff"]: return ["dump","profile"]
    if argv[:3]==["rule","temp","list"] and len(argv)==3: return ["dump","temp-rule"]
    if argv[:3]==["rule","temp","add"]: return ["add-temp-rule",*argv[3:]]
    if argv[:3]==["rule","temp","remove"]: return ["del-temp-rule",*argv[3:]]
    if argv[:3]==["rule","temp","set-policy"]: return ["update-temp-rule",*argv[3:]]
    if argv==["rule","temp","flush"]: return ["flush-temp-rule"]
    if argv[:2]==["watch","speed"]: return ["watch","real-time-speed",*argv[2:]]
    if argv[:2]==["script","evaluate"] and len(argv)>=3:
        path=argv[2]
        try:
            script=Path(path).read_bytes()
        except OSError as e:
            die(f"Cannot read script file {path}: {e}",2)
        tail=argv[3:]
        mock_types={"generic":"0","http-response":"1","http-request":"2","cron":"3","event":"4","rule":"5","dns":"6"}
        if tail:
            if tail[0] not in mock_types:
                die(f"Unknown mock script type: {tail[0]}",2)
            tail=[mock_types[tail[0]],*tail[1:]]
        return ["script","evaluate",base64.b64encode(script).decode(),*tail]
    return argv

class Controller:
    def __init__(self, remote, password, timeout=COMMAND_TIMEOUT):
        self.host,self.port=split_hostport(remote)
        try:
            self.sock=socket.create_connection((self.host,self.port),timeout=8)
            self.sock.settimeout(timeout)
            # Buffered reader: an unbuffered readline() issues one recv() per byte.
            self.fp=self.sock.makefile("rb")
            self.sock.sendall(password.encode()+b"\r\n")
            line=self.fp.readline()
        except (OSError,TimeoutError) as e: die(f"Cannot connect to Surge Controller at {remote}: {e}")
        if not line: die("Controller closed the connection during authentication")
        try: self.welcome=json.loads(line)
        except Exception: die("Invalid Controller welcome response")
        if "error" in self.welcome: die(str(self.welcome["error"]))
        if self.welcome.get("result") != "Welcome to Surge CLI": die("Authorization denied")
    def send(self,argv):
        payload=json.dumps({"argv":argv},ensure_ascii=False,separators=(",",":")).encode()+b"\r\n"
        try: self.sock.sendall(payload)
        except OSError as e: die(f"Failed to send Controller command: {e}")
    def read_one(self, eof_ok=False):
        """Read one JSON frame; on EOF return None when eof_ok (stream end), else fail."""
        try: line=self.fp.readline()
        except socket.timeout: die("The controller command timed out without progress")
        if not line:
            if eof_ok: return None
            die("The controller connection has been closed")
        try: return json.loads(line)
        except json.JSONDecodeError: return {"result":line.decode(errors="replace").rstrip()}
    def read_data(self):
        """Read a data-channel reply (retrieve-data).

        Success: <uint64 little-endian length> CRLF <body bytes>, then the server closes.
        Failure: an ordinary JSON line such as {"error":"Data does not exist"}.
        Returns (body_bytes, None) or (None, error_dict).
        """
        try:
            head=self.fp.read(10)
            if len(head)==10 and head[8:10]==b"\r\n":
                size=struct.unpack("<Q",head[:8])[0]
                body=self.fp.read(size)
                if len(body)!=size: die(f"Truncated data: expected {size} bytes, got {len(body)}")
                return body,None
            line=head+self.fp.readline()
        except socket.timeout: die("The controller command timed out without progress")
        if not line: die("The controller connection has been closed")
        try: value=json.loads(line)
        except json.JSONDecodeError: die(f"Unexpected data-channel reply: {line[:80]!r}")
        return None,value if isinstance(value,dict) else {"error":str(value)}
    def stream(self, finite=False, until_complete=False):
        """Yield stream frames; event envelopes are unwrapped to their data, like the native client.

        finite: stop after a frame with hasMore=false.
        until_complete: stop after the {"result":"complete"} frame (diagnostics).
        """
        previous_timeout=self.sock.gettimeout()
        if not finite:
            self.sock.settimeout(None)
        try:
            while True:
                value=unwrap_event(self.read_one(eof_ok=True))
                if value is None: return
                yield value
                if finite and isinstance(value,dict) and value.get("hasMore") is False:
                    return
                if until_complete and value=={"result":"complete"}:
                    return
        except KeyboardInterrupt:
            return
        finally:
            self.sock.settimeout(previous_timeout)
    def close(self):
        try: self.fp.close()
        except OSError: pass
        try: self.sock.close()
        except OSError: pass

def decode_body(data: bytes):
    """Captured bodies keep their HTTP Content-Encoding; undo gzip/zstd (detected by magic bytes).

    Returns (bytes, note); note names the decoding applied or why the bytes are left as-is.
    """
    try:
        if data[:2]==b"\x1f\x8b": return gzip.decompress(data),"gzip-decoded"
        if data[:4]==b"\x28\xb5\x2f\xfd":
            try:
                from compression import zstd  # Python 3.14+
                return zstd.decompress(data),"zstd-decoded"
            except ImportError:
                if shutil.which("zstd"):
                    p=subprocess.run(["zstd","-dcq"],input=data,capture_output=True)
                    if p.returncode==0: return p.stdout,"zstd-decoded (zstd CLI)"
                return data,"zstd body left compressed (needs Python 3.14+ or the zstd CLI)"
    except Exception as e:
        return data,f"decoding failed, raw bytes written: {e}"
    return data,None

def unwrap_event(frame):
    """Subscription frames arrive as {"event","data","timestamp"}; the native client prints only data."""
    if isinstance(frame,dict) and "event" in frame and "data" in frame:
        return frame["data"]
    return frame

def duration(v):
    try: s=int(v)
    except Exception: return str(v)
    d,s=divmod(s,86400); h,s=divmod(s,3600); m,s=divmod(s,60)
    return " ".join(x for x in (f"{d}d" if d else "",f"{h}h" if h else "",f"{m}m" if m else "",f"{s}s" if s or not (d or h or m) else "") if x)
def onoff(v): return "On" if v else "Off"
def scalar(v):
    if v is None:return "(none)"
    if isinstance(v,bool):return onoff(v)
    return str(v)

def render_status(o):
    started=o.get("start-time")
    st=datetime.fromtimestamp(started).astimezone().strftime("%Y-%m-%d %H:%M:%S %z") if isinstance(started,(int,float)) else scalar(started)
    print(f"Surge {o.get('version','?')} ({o.get('build','?')})")
    print(f"Core: {o.get('core-version','?')}\nController Protocol: {o.get('controller-protocol','?')}")
    print(f"System: {o.get('system','?')} {o.get('system-version','')}")
    print(f"Device: {o.get('device-name','?')} [{o.get('device-identifier','?')}]\n")
    print(f"Profile: {o.get('profile','?')}\nProfile Path: {o.get('profile-path','?')}")
    print(f"Mode: {o.get('mode','?')}\nGlobal Policy: {scalar(o.get('global-policy'))}")
    print(f"Started: {st}\nUptime: {duration(o.get('uptime',0))}\n\nFeatures:")
    for k,v in sorted(o.get("features",{}).items()): print(f"  {k}: {onoff(v)}")
def render_version(o):
    print(f"Surge {o.get('version','?')} ({o.get('build','?')})\nCore: {o.get('core-version','?')}\nController Protocol: {o.get('controller-protocol','?')}\nSystem: {o.get('system','?')} {o.get('system-version','')}\nDevice: {o.get('device-name','?')} [{o.get('device-identifier','?')}]")
def render_group(g):
    print(f"{g.get('name','?')} ({g.get('type','?')})\n  Selected: {scalar(g.get('selected'))}\n  Options:")
    for x in g.get("options",[]):
        details=[]
        if x.get("typeDescription"): details.append(x["typeDescription"])
        if x.get("isGroup"): details.append("Group")
        if not x.get("enabled",True): details.append("disabled")
        tail=f" ({', '.join(details)})" if details else ""
        h=f" [{x['lineHash']}]" if x.get("lineHash") else ""
        print(f"    {x.get('name','?')}{tail}{h}")
def render_rule(o, explain=False):
    if not explain:
        print(f"Matched rule: {o.get('rule','?')}\nPolicy: {o.get('policy','?')}")
        return
    print(f"Matched rule: {o.get('rule','?')}")
    if o.get("steps"):
        print("\nDecision path:")
        for x in o["steps"]:
            print(f"  {x.get('group','?')} ({x.get('type','?')}) -> {x.get('selected','?')}  [{x.get('reason','?')}]")
    print(f"\nFinal policy: {o.get('final','?')} ({o.get('final-type','?')})")
    if o.get("duration-ms") is not None: print(f"Duration: {o['duration-ms']:.2f} ms")
    if o.get("notes"):
        print("\nNotes:")
        for n in o["notes"]: print(f"  {n}")
def render_dns(o):
    print(f"Domain: {o.get('domain','?')}\nIPv4: {', '.join(o.get('v4Addresses',[])) or '(none)'}\nIPv6: {', '.join(o.get('v6Addresses',[])) or '(none)'}\nServer: {scalar(o.get('server'))}\nInterface: {scalar(o.get('interface'))}\nPath: {scalar(o.get('path'))}\nDuration: {o.get('duration-ms','?')} ms")
    if o.get("logs"):
        print("Logs:")
        for x in o["logs"]: print(f"  {x}")
def render_vmnet(argv,o):
    sub=argv[1] if len(argv)>1 else ""
    if sub=="status":
        fields=(
            ("Running","running",lambda v:"yes" if v else "no"),
            ("Main interface","main-interface",scalar),("Main interface MAC","main-interface-mac",scalar),
            ("VMNET MAC","self-mac",scalar),("MTU","mtu",scalar),("IPv4 self","self-ip",scalar),
            ("IPv4 router","router-ip",scalar),("IPv6 link-local","self-ipv6-link-local",scalar),
            ("IPv6 global","self-ipv6-global",scalar),("IPv6 prefix","ipv6-prefix",scalar),
            ("IPv6 router","router-ipv6",scalar),("ARP entries","arp-entries",scalar),
            ("NDP entries","nd-entries",scalar),("RA clients","ra-clients",scalar),
            ("RA blacklist","ra-blacklist",scalar),("Known routers","known-routers",scalar),
        )
        for title,key,fmt in fields: print(f"{title}: {fmt(o.get(key))}")
        return
    if sub in ("arp","ndp"):
        entries=o.get("entries",[])
        if not entries: print("(none)")
        for x in entries: print(f"{x.get('ip','?'):<44} {x.get('mac','?')}  (age {x.get('age-seconds','?')}s)")
        return
    if sub=="ra":
        for title,key in (("RA takeover clients","clients"),("Known routers","routers"),("Blacklisted clients","blacklist")):
            values=o.get(key,[]); print(f"{title} ({len(values)}):")
            if not values: print("  (none)")
            for x in values: print("  "+json.dumps(x,ensure_ascii=False,separators=(",",":")))
            print()
        return
    print(json.dumps(o,ensure_ascii=False,indent=2))

def render_summary(o):
    sections=o.get("sections",[])
    if not isinstance(sections,list):
        print(json.dumps(o,ensure_ascii=False,indent=2)); return
    for section in sections:
        print(f"{section.get('section','Summary')}:")
        for line in section.get("lines",[]):
            content=str(line.get("content",""))
            parts=content.splitlines() or [""]
            print(f"  {line.get('title','?')}: {parts[0]}")
            for extra in parts[1:]: print(f"    {extra}")
        print()

def render_profile_diff(o):
    original=o.get("originalProfile")
    effective=o.get("profile")
    if not isinstance(original,str) or not isinstance(effective,str):
        print(json.dumps(o,ensure_ascii=False,indent=2)); return
    sys.stdout.writelines(difflib.unified_diff(
        original.splitlines(keepends=True),effective.splitlines(keepends=True),
        fromfile="original",tofile="effective"
    ))

def render(argv,o,original_argv=None):
    shown=original_argv or argv
    key=tuple(argv[:2]); cmd=argv[0] if argv else ""
    if shown==["summary"]: return render_summary(o)
    if shown==["profile","diff"]: return render_profile_diff(o)
    if cmd=="status": return render_status(o)
    if cmd=="version": return render_version(o)
    if cmd=="mode" and "mode" in o: print(o["mode"]); return
    if cmd=="global-policy" and "policy" in o: print(scalar(o["policy"])); return
    if cmd=="feature" and "features" in o:
        for k,v in sorted(o["features"].items()): print(f"{k}: {onoff(v)}")
        return
    if key==("policy-group","list") and "groups" in o:
        for g in o["groups"]: print(f"{g.get('name','?')}: {scalar(g.get('selected'))} ({g.get('type','?')})")
        return
    if key==("policy-group","get"):
        g=o.get("group",o)
        if isinstance(g,dict): return render_group(g)
    if key in (("rule","match"),("rule","explain")): return render_rule(o,key[1]=="explain")
    if cmd=="vmnet": return render_vmnet(argv,o)
    if key in (("dns","lookup"),("dns","trace")): return render_dns(o)
    if cmd=="profile" and "profile" in o and len(o)==1: print(o["profile"]); return
    if key==("module","list"):
        enabled=set(o.get("enabled",[])); print("Modules:")
        for n in o.get("available",[]): print(f"  {'[x]' if n in enabled else '[ ]'} {n}")
        return
    if cmd=="geoip":
        for k in ("address","country","asn","organization","geoip-db-date","asn-db-date"):
            if k in o: print(f"{k}: {scalar(o[k])}")
        return
    if key==("dump","performance"):
        for k,v in o.items(): print(f"{k}: {v}")
        return
    if "result" in o and len(o)==1: print(scalar(o["result"])); return
    print(json.dumps(o,ensure_ascii=False,indent=2))

def main():
    raw,remote,stdin_mode,argv=parse_cli(sys.argv[1:])
    if not argv: print(MAIN_HELP); return
    if argv[0]=="help":
        key=" ".join(argv[1:3]) if " ".join(argv[1:3]) in HELP else (argv[1] if len(argv)>1 else "")
        print(HELP.get(key,MAIN_HELP)); return
    if any(tuple(argv[:len(k)])==k for k in NATIVE_ONLY_COMMANDS):
        die(f"`{' '.join(argv[:2])}` runs offline in the native surge-cli and is unavailable in the Python backend.",2)
    original_argv=list(argv)
    argv=normalize(argv)
    c=Controller(remote,credential(stdin_mode))
    try:
        c.send(argv)
        if argv[0]=="retrieve-data":
            body,err=c.read_data()
            if err:
                print(json.dumps(err,ensure_ascii=False,separators=(",",":")) if raw else f"Error: {err.get('error',err)}",file=sys.stderr)
                raise SystemExit(1)
            body,note=decode_body(body)
            if note: print(f"retrieve-data: {note}",file=sys.stderr)
            sys.stdout.buffer.write(body); sys.stdout.buffer.flush()
            raise SystemExit(0)
        continuous=(len(argv)>1 and argv[0]=="watch") or any(tuple(argv[:len(k)])==k for k in CONTINUOUS_COMMANDS)
        finite=any(tuple(argv[:len(k)])==k for k in FINITE_STREAM_COMMANDS)
        until_complete=argv[:1]==["diagnostics"]
        values=c.stream(finite=finite,until_complete=until_complete) if continuous or finite else (c.read_one(),)
        code=0
        for o in values:
            if isinstance(o,dict) and o.get("error"):
                print(json.dumps(o,ensure_ascii=False,separators=(",",":")) if raw else f"Error: {o['error']}",file=sys.stderr)
                code=1
                break
            if raw: print(json.dumps(o,ensure_ascii=False,separators=(",",":")),flush=True)
            else: render(argv,o,original_argv)
        raise SystemExit(code)
    finally: c.close()
if __name__=="__main__": main()
