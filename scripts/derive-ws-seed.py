#!/usr/bin/env python3
"""Derive peers.ws.json — the browser-dialable subset of peers.seed.json.

Browsers can only dial WebSocket (no raw TCP), so the browser cold-start
seed is the /ws[s] subset of the TCP harvest. But two extra filters are
ESSENTIAL, learned the hard way:

  1. REACHABILITY. The `--healthcheck` step dialed every peer and recorded
     the outcome. Mainnet /wss is scarce and flaky (AutoTLS SNI hostnames
     rotate every ~2-3h), so the raw ws subset is mostly DEAD underlays.
     Keeping them shipped a browser seed where ~90% of dials fail
     (`Firefox can't establish a connection`), starving the upload pool.
     Keep ONLY peers the healthcheck just reached: `last_dial_success_unix`
     set AND no newer failure.

  2. UNIQUE IP. A handful of operators run many bee nodes on ONE host
     (e.g. 3 Hetzner IPs accounted for 93% of a prior ws seed, each with
     dozens of rotated SNI overlays). Keeping many overlays per host is
     actively HARMFUL in the browser: Firefox's
     `network.websocket.delay-failed-reconnects` throttles (and largely
     serializes) reconnects to the same host:port after any failed WS
     attempt, with exponential backoff. So dialing 100 overlays behind 3
     IPs isn't 100 parallel dials — it's 3 hosts' worth of backoff-delayed,
     serialized attempts, which is exactly the slow "can't establish a
     connection" trickle observed. Keep exactly ONE overlay per /32 so the
     browser dials distinct hosts in parallel and one host's failures never
     penalize another's dials. (The TCP seed — peers.seed.json — is NOT
     deduped: raw TCP has no per-host browser backoff and native benefits
     from the redundancy.)

Dial-cache annotations ARE preserved (last_dial_*): the browser ranks
known-good peers first, and hourly timestamp churn in the committed file is
fine (`[skip ci]` keeps it from triggering other workflows).
"""

import collections
import json
import re
import sys

# Exactly ONE overlay per /32 IPv4 (one physical host / operator):
# avoids Firefox's per-host failed-reconnect backoff (see above).
PER_IP_CAP = 1

# With one overlay per IP, the kept count IS the number of distinct
# reachable /wss hosts on mainnet — genuinely scarce (only a handful of
# operators enable AutoTLS). A degenerate seed is worse than a slightly
# stale one, so keep the committed file if fewer than 3 hosts came back. If
# this trips repeatedly, mainnet /wss host availability itself is the
# bottleneck, not this script.
MIN_HOSTS = 3


def ipv4(underlays):
    for u in underlays:
        m = re.search(r"/ip4/([0-9.]+)/", u)
        if m:
            return m.group(1)
    return None


def reachable(p):
    # Healthcheck-verified alive: a success on record, and no failure that
    # is newer than that success.
    s = p.get("last_dial_success_unix")
    f = p.get("last_dial_failure_unix")
    if not s:
        return False
    if f and f > s:
        return False
    return True


def main():
    seed = json.load(open("peers.seed.json"))

    # Collect reachable ws peers, best-RTT first so the per-IP cap keeps
    # the fastest overlays of each host rather than an arbitrary slice.
    cand = []
    ws_total = 0
    for overlay, p in seed["peers"].items():
        ws = [u for u in p["underlays"] if "/ws" in u]
        if not ws:
            continue
        ws_total += 1
        if not reachable(p):
            continue
        rtt = p.get("last_dial_rtt_ms")
        rtt = rtt if isinstance(rtt, int) else 1 << 30
        cand.append((rtt, overlay, p, ws))
    cand.sort(key=lambda t: t[0])

    out = {}
    per_ip = collections.Counter()
    for rtt, overlay, p, ws in cand:
        ip = ipv4(ws) or "?"
        if per_ip[ip] >= PER_IP_CAP:
            continue
        per_ip[ip] += 1
        out[overlay] = {
            "overlay": p["overlay"],
            "underlays": ws,
            "eth_address": p.get("eth_address"),
            "nonce": p.get("nonce"),
            # Preserve reachability so the browser prioritizes known-good.
            "last_dial_success_unix": p.get("last_dial_success_unix"),
            "last_dial_failure_unix": p.get("last_dial_failure_unix"),
            "last_dial_rtt_ms": p.get("last_dial_rtt_ms"),
            "consecutive_failures": p.get("consecutive_failures", 0),
        }
    count = len(out)  # == number of distinct reachable /wss hosts (1/IP)
    print(
        f"ws seed: {ws_total} ws peers in harvest, "
        f"{len(cand)} reachable, kept {count} unique-IP host(s)"
    )

    if count < MIN_HOSTS:
        print(
            f"::warning::Only {count} reachable /wss host(s) (<{MIN_HOSTS}); "
            f"keeping existing peers.ws.json."
        )
        return 0

    with open("peers.ws.json", "w") as f:
        json.dump({"peers": out}, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
