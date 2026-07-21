# ACA-Py DIDComm throughput — stock vs DIDComm memory cache

**ACA-Py:** `py3.13-1.6.0` (Askar)  
**Workload:** 10 000 DIDComm basic messages, 20 concurrent senders  
**Host:** 12 vCPU / ~16 GB RAM (Docker on WSL2)  
**Author:** Patrick St-Louis  

Full investigation (isolation matrix, TTL/LRU hardening, multi-replica scaling, inbound appendix): see DigiCred’s [`ACAPY_THROUGHPUT_REPORT.md`](https://github.com/DigiCred-Holdings/owl-akrida/blob/benchmark/basic-msg-10k/docs/ACAPY_THROUGHPUT_REPORT.md) on `benchmark/basic-msg-10k`.

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

### Against real Credo holders

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

One ACA-Py process with the DIDComm memory cache reaches **~220–242 msg/s** at under one core — well above a cited ~170 msg/s Credo figure for a single agent.

### Inbound (same shared cache)

Replaying authcrypt BasicMessages at the DIDComm inbound endpoint (10k msgs, 20 concurrent):

| Inbound path | Handled msg/s | Hot unpack |
|---|---:|---:|
| Stock | 174.7 | — |
| Memory cache | **210.5** | **0.80 ms** (vs ~53 ms cold) |

About **~1.2×** on the full receive pipeline; hot unpack is ~66× faster than cold.

---

## Security considerations

The DIDComm memory cache does **not** weaken the DIDComm v1 envelope: every message still gets a fresh CEK, nonce, and AEAD. Holders see the same wire format as stock ACA-Py.

What changes is **where send/unpack material lives between messages**. The cache holds per-connection crypto state (including a sender key handle used for packing, and the X25519 material used for authcrypt unpack). That is a deliberate performance tradeoff — secret material stays reachable in process memory longer than a pure per-send Askar fetch.

Mitigations measured in the full report:

- **Active TTL** (default **30 s**) plus background eviction (~1 s) so idle entries — and their key handles — drain after traffic stops. TTL sweeps down to **10 s** showed no meaningful throughput regression, so operators can tighten retention if required.
- **Tenant-scoped keys** `(local_tenant_wallet_id, connection_id)` so multitenant wallets do not share cache entries across subwallets.
- **LRU cap** (default 8192 entries) to bound memory and stale entries under many connections.
- **Wallet-removal / invalidation hooks** so deleted wallets drop their cache entries.

On the inbound path (when enabled), a cache hit still requires the exact `(wallet_id, recipient verkey)` index entry; authcrypt sender verification still runs; the `ConnRecord` shortcut is only taken for authcrypt (not anoncrypt). Inbound integration uses a supported wire-format binding plus a version-sensitive override of connection lookup — re-verify (or disable inbound caching) when upgrading ACA-Py.

---

## Takeaways

1. Stock ACA-Py’s basic-message send ceiling is **pipeline overhead**, not crypto or Postgres.
2. A DIDComm memory cache of per-connection send material gives **~1.35–1.5×** send throughput against real holders and **~3×** vs stock when the recipient is cheap (~70 → ~242 msg/s).
3. The same cache can lift inbound handling **~1.2×** when enabled.
4. Treat **~200–240 msg/s per process** (with the cache) as a working single-process budget; scale horizontally for more.
