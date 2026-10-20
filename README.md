# hoverfly-peers

Peerlists for the [hoverfly](https://github.com/omnipin/hoverfly) Swarm light client.

This repo holds **data, not code** — the two peerlists hoverfly boots from — and
nothing else. It exists as a separate repo so the hourly refresh doesn't churn
the hoverfly source history: the files are regenerated every hour, and a
consumer that wants a *fresh* peerlist should fetch them from here rather than
from a release tarball.

## Files

| File | What it is |
| --- | --- |
| `peers.seed.json` | The TCP peerlist — every peer the last harvest reached, with reachability annotations (`last_dial_success_unix`, `last_dial_rtt_ms`, …). This is what `hoverfly daemon --peerlist` / `hoverfly upload --peerlist` take. |
| `peers.ws.json` | The browser-dialable subset of the same harvest — only `/ws`/`/wss` underlays, only peers the healthcheck just reached, and only **one overlay per /32 IP** (Firefox's per-host failed-reconnect backoff turns 100 overlays on 3 hosts into 3 serialized streams). This is the cold-start seed the gateway and the upload dApp serve/fetch. |

## Fetching them

```sh
curl -fsSL -o peers.json https://raw.githubusercontent.com/omnipin/hoverfly-peers/main/peers.seed.json
curl -fsSL -o peers.ws.json https://raw.githubusercontent.com/omnipin/hoverfly-peers/main/peers.ws.json
```

The hoverfly release tarballs bundle a snapshot of `peers.seed.json` as a
convenient fallback; it is frozen at release time, so prefer the raw URL above
whenever you can reach the network.

## How they're produced

`.github/workflows/refresh-peers.yml` runs hourly:

1. Downloads the latest `hoverfly` release binary.
2. Runs `hoverfly discover --rounds 5 --healthcheck` against the mainnet
   bootnode → `peers.seed.json`.
3. Derives `peers.ws.json` from it with `scripts/derive-ws-seed.py`.
4. Commits both with `[skip ci]`.

Two sanity gates keep a bad network round from replacing a good seed: the
harvest must yield at least 500 peers, and the derived browser seed must cover
at least 3 distinct reachable `/wss` hosts. If either trips, the previous
files are kept.

Mainnet `/ws` peers go stale within ~2–3 hours (AutoTLS SNI addresses rotate,
nodes churn), which is why the cadence is hourly.

## Manual runs

The workflow can be triggered by hand from the Actions tab, with `rounds` and
`discover_concurrency` overridable.
