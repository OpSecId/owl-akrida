# ACA-Py DIDComm throughput — stock vs `didcomm_fastpath` cache

**ACA-Py:** `py3.13-1.6.0` (Askar)  
**Workload:** 10 000 DIDComm basic messages, 20 concurrent senders  
**Host:** 12 vCPU / ~16 GB RAM (Docker on WSL2)  
**Author:** Patrick St-Louis  

Full investigation (isolation matrix, TTL/LRU hardening, Kanon, multi-replica scaling, inbound appendix): see DigiCred’s [`ACAPY_THROUGHPUT_REPORT.md`](https://github.com/DigiCred-Holdings/owl-akrida/blob/benchmark/basic-msg-10k/docs/ACAPY_THROUGHPUT_REPORT.md) on `benchmark/basic-msg-10k`.

---

## What we measured

Stock ACA-Py 1.6.0 tops out around **~58–70 msg/s** per process for DIDComm basic-message send (admin path **70 msg/s** on Postgres; e2e receipt a bit lower). That is a real ceiling — not the storage backend, not the mediator, and not DIDComm crypto (pack already runs in a thread pool).

Profiling points at **per-send pipeline overhead**: Askar session / FFI lifecycle (~42% of sampled self-time) and asyncio (~27%). Crypto on the main thread is negligible.

---

## What `didcomm_fastpath` changes

Same DIDComm v1 wire format (fresh CEK / nonce / AEAD every message). After the first send on a connection, the plugin **caches** endpoint, recipient/routing keys, sender key material, Ed25519→X25519 conversions, and sealed-sender blob.

Later sends: build JSON → pack in a thread pool → HTTP POST on a keep-alive session — **no** per-send `ConnRecord` fetch, Askar session, or outbound-queue round-trip.

---

## Gain from the DIDComm send cache

### Against real Credo holders

| Path | Steady msg/s | Issuer CPU (mean) |
|---|---:|---:|
| Stock admin send | 70.0 | 124% |
| Fast-path admin send | **94.4** | 106% |
| Fast-path e2e (receipt) | **104.9** | — |

Roughly **~1.35×** (admin) / **~1.5×** (e2e) more throughput at **lower CPU per message**, with wire-valid delivery end-to-end.

> Against co-located holders, the load generator (holders do ~10× issuer CPU per message) often bounds the run. The numbers below isolate the issuer.

### Issuer ceiling (cheap recipient / mock sink)

Packing still uses real connection keys; the sink returns `200` without unpacking:

| Connections | Steady msg/s |
|---:|---:|
| 20 | 220.6 |
| 40 | 227.1 |
| 60 | **241.9** |

One fast-path process reaches **~220–242 msg/s** at under one core — well above a cited ~170 msg/s Credo figure for a single agent.

### Inbound (same shared cache)

Replaying authcrypt BasicMessages at the DIDComm inbound endpoint (10k msgs, 20 concurrent):

| Inbound path | Handled msg/s | Hot unpack |
|---|---:|---:|
| Stock | 174.7 | — |
| Fast path | **210.5** | **0.80 ms** (vs ~53 ms cold) |

About **~1.2×** on the full receive pipeline; hot unpack is ~66× faster than cold.

---

## Takeaways

1. Stock ACA-Py’s basic-message send ceiling is **pipeline overhead**, not crypto or Postgres.
2. Caching per-connection DIDComm send material (`didcomm_fastpath`) gives **~1.35–1.5×** send throughput against real holders and **~3×** vs stock when the recipient is cheap (~70 → ~242 msg/s).
3. The same cache can lift inbound handling **~1.2×** when enabled.
4. Treat **~200–240 msg/s per fast-path process** as a working single-process budget; scale horizontally for more.
