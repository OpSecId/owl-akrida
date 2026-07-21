# ACA-Py DIDComm throughput — stock vs DIDComm memory cache

**ACA-Py:** `py3.13-1.6.0` (Askar)  
**Workload:** 10 000 DIDComm basic messages, 20 concurrent senders  
**Host:** 12 vCPU / ~16 GB RAM (Docker on WSL2)  
**Author:** Patrick St-Louis  

---

## What we measured

Stock ACA-Py 1.6.0 tops out around **~58–70 msg/s** per process for DIDComm basic-message send (admin path **70 msg/s** on Postgres; e2e receipt a bit lower). That is a real ceiling — not the storage backend, not the mediator, and not DIDComm crypto (pack already runs in a thread pool).

Profiling points at **per-send pipeline overhead**: Askar session / FFI lifecycle (~42% of sampled self-time) and asyncio (~27%). Crypto on the main thread is negligible.

---

## What the DIDComm memory cache changes

Same DIDComm v1 wire format (fresh CEK / nonce / AEAD every message). After the first send on a connection, a **DIDComm memory cache** keeps endpoint, recipient/routing keys, sender key material, Ed25519→X25519 conversions, and sealed-sender blob in process memory.

Later sends: build JSON → pack in a thread pool → HTTP POST on a keep-alive session — **no** per-send `ConnRecord` fetch, Askar session, or outbound-queue round-trip.

---

## Gain from the DIDComm memory cache

### Against real holders

| Path | Steady msg/s | Issuer CPU (mean) |
|---|---:|---:|
| Stock admin send | 70.0 | 124% |
| Cached admin send | **94.4** | 106% |
| Cached e2e (receipt) | **104.9** | — |

Roughly **~1.35×** (admin) / **~1.5×** (e2e) more throughput at **lower CPU per message**, with wire-valid delivery end-to-end.

> Against co-located holders, the load generator (holders do ~10× issuer CPU per message) often bounds the run. The numbers below isolate the issuer.

### Issuer ceiling (cheap recipient / mock sink)

Packing still uses real connection keys; the sink returns `200` without unpacking:

| Connections | Steady msg/s |
|---:|---:|
| 20 | 220.6 |
| 40 | 227.1 |
| 60 | **241.9** |

One ACA-Py process with the DIDComm memory cache reaches **~220–242 msg/s** at under one core.

### Inbound (same shared cache)

Replaying authcrypt BasicMessages at the DIDComm inbound endpoint (10k msgs, 20 concurrent):

| Inbound path | Handled msg/s | Hot unpack |
|---|---:|---:|
| Stock | 174.7 | — |
| Memory cache | **210.5** | **0.80 ms** (vs ~53 ms cold) |

About **~1.2×** on the full receive pipeline; hot unpack is ~66× faster than cold.

---

## TTL / LRU hardening

To limit how long cached sender key handles stay reachable, the memory cache uses an **active TTL**, **background eviction**, **tenant-scoped keys**, and an **LRU entry cap**.

**Defaults (after hardening):**

| Knob | Default | Role |
|---|---|---|
| Active TTL | **30 s** | Idle entries expire; key handles disposed with the entry |
| Background sweep | ~1 s | Evicts expired entries without waiting for the next access |
| Cache key | `(local_tenant_wallet_id, connection_id)` | Isolates multitenant subwallets (`wallet_id` is the local ACA-Py tenant, not the remote peer) |
| LRU max entries | **8192** | Bound by peak concurrent *active* connections, not lifetime total |
| Invalidation | wallet-removal hook | Drops all entries for a deleted wallet |

### TTL sweep (real-holder admin path, 10k messages, 20 connections)

| TTL | Steady msg/s | Cold resolves | p50 / p95 latency |
|---:|---:|---:|---:|
| 300 s | 93.83 | 20 | 200 / 310 ms |
| 60 s | **94.72** | 40 | 200 / 290 ms |
| 30 s | 92.77 | 80 | 200 / 280 ms |
| 10 s | 93.67 | 220 | 200 / 280 ms |

Zero failures across the sweep. Throughput stayed within a **~2% band**, so even **10-second** refreshes (11× more cold resolves than 300 s) did not measurably hurt this workload. **30 s** is the default: performance-safe and long enough to keep connections warm across multi-step flows.

### Post-hardening check (TTL=30 s, LRU max=8192)

After tenant-scoped keys, active TTL, LRU bounds, key-handle disposal, and the wallet-removal hook, the 10k matrix was re-run — **no regression**:

| Path | Steady msg/s | Failures | Cache signal |
|---|---:|---:|---|
| Cached e2e (real holders, 20 conns) | **102.3** | 0 | `evictions_lru=0`; TTL expirations on idle |
| Cached mock sink (20 conns) | **227.3** | 0 | Cache drained to 0 entries after idle via active sweep |

`cache_entries` stayed at 20 (≪ 8192, so LRU never fired). After traffic stopped, the background sweeper reclaimed every idle entry and its sender key material within the 30 s TTL.

---

## Multi-replica scaling (shared Postgres, mock sink)

To check whether the per-process ceiling is additive, the cached mock-sink workload was run across **N = 1, 2, 3 issuer replicas** sharing one Askar Postgres wallet. Each Locust user is sticky to one replica (setup and sends stay on the same process); each replica has its own DIDComm inbound endpoint and its own **per-process** DIDComm memory cache. Offered load: **20 Locust users per replica**.

| Replicas | Users | Aggregate msg/s | Per-replica msg/s | vs 1× |
|---:|---:|---:|---:|---:|
| 1 | 20 | **185.3** | 185.3 | 1.00× |
| 2 | 40 | **250.7** | 125.4 | 1.35× |
| 3 | 60 | 243.4 | 81.1 | 1.31× |

- **Shared-wallet + sticky routing works.** Sends split evenly across replicas (N=2 ≈ 5019 / 4981; N=3 ≈ 3349 / 3321 / 3330) and every message landed at the mock sink (0 failures).
- **Aggregate peaks ~250 msg/s on this host, then plateaus.** Locust warned about CPU above 90% at N=2 and N=3 — the load generator (and holder agents used for connection setup) saturated the 12-core box. Mean per-send latency on each issuer actually *dropped* at N=3 (≈19 ms vs ≈28 ms at N=1), so the issuers were under-loaded; the **host** was the limiter, not Postgres.
- **What this proves on one box:** multi-replica shared-wallet send is correct and adds capacity until the host is full. It does **not** prove linear N× scaling — that needs the load generator (and ideally the replicas) on separate hosts.

---

## Security considerations

The DIDComm memory cache does **not** weaken the DIDComm v1 envelope: every message still gets a fresh CEK, nonce, and AEAD. Holders see the same wire format as stock ACA-Py.

What changes is **where send/unpack material lives between messages**. The cache holds per-connection crypto state (including a sender key handle used for packing, and the X25519 material used for authcrypt unpack). That is a deliberate performance tradeoff — secret material stays reachable in process memory longer than a pure per-send Askar fetch. The TTL/LRU controls above are how that window is bounded.

On the inbound path (when enabled), a cache hit still requires the exact `(wallet_id, recipient verkey)` index entry; authcrypt sender verification still runs; the `ConnRecord` shortcut is only taken for authcrypt (not anoncrypt). Inbound integration uses a supported wire-format binding plus a version-sensitive override of connection lookup — re-verify (or disable inbound caching) when upgrading ACA-Py.

---

## Takeaways

1. Stock ACA-Py’s basic-message send ceiling is **pipeline overhead**, not crypto or Postgres.
2. A DIDComm memory cache of per-connection send material gives **~1.35–1.5×** send throughput against real holders and **~3×** vs stock when the recipient is cheap (~70 → ~242 msg/s).
3. The same cache can lift inbound handling **~1.2×** when enabled.
4. Active TTL (default 30 s) and LRU (default 8192 entries) do not cost measurable throughput; tighten TTL freely if a shorter secret-retention window is required.
5. Treat **~200–240 msg/s per process** (with the cache) as a working single-process budget; scale horizontally behind shared Postgres. On one host, aggregate throughput plateaus once the load generator fills the cores (~250 msg/s here) — true N× needs separate hosts.
