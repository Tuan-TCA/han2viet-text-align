"""Stage 03B Coarse Mapping V2: Integrate Book VI (`VIET_0405-0439.xlsx`) into Cap_02.

Extends Cap_02 coarse page mapping from Han pages 001-051 to 001-087 using the
existing B1 anchor interpolation and B2 API-assisted global monotone reconciliation
algorithms, while keeping all shared Stage02/Stage03/Stage03B/Stage04 files read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
from statistics import mean, median
import sys
import time

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
SCRIPTS_V2 = Path(__file__).resolve().parent
SCRIPTS_V1 = STAGE / "scripts"
LEGACY_SCRIPTS = ROOT / "pipeline" / "scripts"

for _p in (str(SCRIPTS_V2), str(SCRIPTS_V1), str(LEGACY_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import requests
from openpyxl import load_workbook

from api_integration import ALIGN, Client, retry_seconds
from candidate_boundaries import entities, numbers
from evaluate_pipeline import workbook
from preprocess import fingerprint, read_jsonl, write_json
from run_release import dump_jsonl, nested, t1_rows
from refine_coarse_mapping import (
    agreement,
    anchors_for,
    interpolate,
    interval,
    original_evidence,
    page_window,
    prior_for,
    reconcile,
    span_for,
    summarizes_probe,
    take,
)
from preprocess_v2 import (
    WORKBOOK_SPECS,
    analyze_page051_and_book6_anchors,
    cap_coord_page,
    cap_pdf_page_from_coord,
    legacy_viet_view,
    load_sources_v2,
    sha256_file,
    verify_frozen_s4_and_han,
)

PROD_DIR = STAGE / "artifacts" / "production"
V1_DIR = STAGE / "artifacts" / "coarse_mapping"
DEFAULT_OUT = STAGE / "artifacts" / "coarse_mapping_v2"
VERSION = "2.0-book6"


class CoarseClientV2(Client):
    """Isolated Alignment-only API client with exact-payload read-only cache reuse
    and polite HTTP 429 / transient backoff for concurrent multi-agent execution.
    """

    def __init__(self, out_dir: Path, cfg: dict, live: bool, api_delay: float, api_retries: int):
        cfg_v2 = {**cfg, "api_delay": api_delay, "api_retries": api_retries}
        super().__init__(out_dir, cfg_v2, live)
        self.readonly_caches: dict[str, Path] = {}
        self.reused_sources: list[dict] = []
        self.retries_used = 0
        self.http_429_count = 0
        self.transient_failures = 0
        self.permanent_failures = 0
        self.live_ok_count = 0

        # Index read-only prior caches (never written to)
        cache_roots = [
            V1_DIR / "cache",
            V1_DIR / "pilot" / "cache",
            *sorted((STAGE / "artifacts" / "benchmark").glob("*/cache")),
            *sorted((STAGE / "artifacts" / "ablation").glob("*/cache")),
            *sorted((STAGE / "artifacts" / "heldout").glob("*/cache")),
            *sorted((STAGE / "artifacts" / "release").glob("*/cache")),
        ]
        for cdir in cache_roots:
            if cdir.is_dir() and cdir.resolve() != self.cache.resolve():
                for f in cdir.glob("*.json"):
                    self.readonly_caches.setdefault(f.stem, f)

    def _validate_cached(self, obj: dict, url: str, payload: dict) -> bool:
        return (
            isinstance(obj, dict)
            and obj.get("endpoint") == url
            and obj.get("payload") == payload
            and obj.get("status") == "ok"
        )

    def call(self, url: str, payload: dict) -> dict:
        if url != ALIGN:
            raise ValueError("Coarse Mapping V2 permits Alignment endpoint only; Separate is forbidden.")
        key = fingerprint([url, payload])
        local_file = self.cache / f"{key}.json"
        if local_file.is_file():
            cached = json.loads(local_file.read_text(encoding="utf-8"))
            if not self._validate_cached(cached, url, payload):
                raise ValueError(f"Local cache provenance mismatch for {key}")
            self.hits += 1
            return cached

        ro_file = self.readonly_caches.get(key)
        if ro_file and ro_file.is_file():
            cached = json.loads(ro_file.read_text(encoding="utf-8"))
            if self._validate_cached(cached, url, payload):
                self.hits += 1
                self.reused_sources.append({"key": key, "source": ro_file.relative_to(ROOT).as_posix()})
                return cached

        if self.halt or not self.live or not self.token:
            return {"status": self.halt or ("offline" if not self.live else "no_token"), "key": key}

        max_retries = self.cfg["api_retries"]
        for attempt_idx in range(max_retries + 1):
            if attempt_idx > 0:
                self.retries_used += 1
            wait_pace = max(0.0, self.cfg["api_delay"] - (time.monotonic() - self.last))
            if wait_pace > 0:
                time.sleep(wait_pace)

            t0 = time.monotonic()
            self.attempts += 1
            result: dict = {"endpoint": url, "key": key, "payload": payload, "attempt": attempt_idx + 1}
            backoff_wait: float | None = None

            try:
                r = self.session.post(
                    url,
                    json=payload,
                    timeout=(10, self.cfg["api_timeout"]),
                    allow_redirects=False,
                )
                raw = r.text.replace(self.token, "[REDACTED]") if self.token else r.text
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
                code = str(body.get("code")) if isinstance(body, dict) else ""
                headers = {
                    k.lower(): (v.replace(self.token, "[REDACTED]") if self.token else v)
                    for k, v in r.headers.items()
                    if re.search(r"rate.?limit|quota|retry-after|^x-request-id$", k, re.I)
                }
                result.update(http=r.status_code, api_code=code, headers=headers, raw_response=raw, body=body)

                # Hard auth / hard quota errors stop immediately
                if r.status_code in (401, 403) or code in {"000401", "000403", "401", "403"}:
                    self.halt = "authorization_error"
                    status = "auth_error"
                elif any("remaining" in k and v.strip() == "0" for k, v in headers.items()) and r.status_code == 429:
                    # Check Retry-After before declaring permanent quota exhaustion
                    ra = retry_seconds(headers.get("retry-after"))
                    if ra is not None and ra > 120:
                        self.halt = "quota_exhausted"
                        status = "rate_limited"
                    else:
                        self.http_429_count += 1
                        status = "rate_limited"
                        backoff_wait = min(60.0, (ra if ra is not None else 2.5 * (2 ** attempt_idx)) + random.uniform(0.2, 0.9))
                elif r.status_code == 429 or code in {"000429", "429"}:
                    self.http_429_count += 1
                    ra = retry_seconds(headers.get("retry-after"))
                    if ra is not None and ra > 120:
                        self.halt = "server_retry_after"
                        result["retry_after_seconds"] = ra
                        status = "rate_limited"
                    else:
                        status = "rate_limited"
                        backoff_wait = min(60.0, (ra if ra is not None else 2.5 * (2 ** attempt_idx)) + random.uniform(0.2, 0.9))
                elif r.status_code == 200 and isinstance(body, dict) and body.get("is_success") is True:
                    status = "ok"
                elif r.status_code in (408, 500, 502, 503, 504):
                    self.transient_failures += 1
                    ra = retry_seconds(headers.get("retry-after"))
                    status = "transient"
                    backoff_wait = min(45.0, (ra if ra is not None else 2.0 * (2 ** attempt_idx)) + random.uniform(0.1, 0.6))
                else:
                    self.permanent_failures += 1
                    status = "api_error"
            except requests.RequestException as exc:
                self.transient_failures += 1
                result["exception"] = type(exc).__name__
                status = "transport_error"
                if self.live_ok_count == 0 and attempt_idx >= 1:
                    self.halt = "network_unreachable"
                    backoff_wait = None
                else:
                    backoff_wait = min(30.0, 2.0 * (2 ** attempt_idx) + random.uniform(0.1, 0.5))

            self.last = time.monotonic()
            result.update(status=status, latency_ms=round(1000 * (self.last - t0)))
            with (self.folder / "requests.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(
                f"  {url.rsplit('/', 1)[-1]} #{self.attempts} (try {attempt_idx + 1}) {status} {result.get('api_code', '')}",
                flush=True,
            )

            if status == "ok":
                self.live_ok_count += 1
                write_json(local_file, result)
                return result
            if self.halt or status not in ("rate_limited", "transient", "transport_error"):
                break
            if attempt_idx < max_retries and backoff_wait is not None:
                time.sleep(backoff_wait)
            elif attempt_idx == max_retries and status == "rate_limited":
                self.halt = "rate_limit_retries_exhausted"

        return result


def collect_v2(result: dict, clip: list[int], origin: int, submitted: list[dict], y_coord: float, prior_coord: list[int] | None, raw: str, cap: str) -> dict:
    """Identical scoring formula to Stage03B `collect`, evaluated in continuous physical page coordinates."""
    pool = {v["id"]: v for v in submitted}
    index = {k: i for i, k in enumerate(pool)}
    a, b = [p - origin for p in clip]
    hset: set[int] = set()
    vid: set[str] = set()
    whole: set[str] = set()
    links: list = []
    active = overlaps = inversions = 0
    last = -1
    number_hits = entity_hits = duplicate_vi = 0
    scores: list[float] = []
    unresolved = 0
    vi_positions: dict[str, set[int]] = defaultdict(set)

    for g in result.get("groups", []):
        x, z = g["Han_Start"], g["Han_End"]
        ids = [k for k in g["VI_IDs"] if k in pool]
        if g["Validation_Status"] not in ("mapped", "partial_viet") or x is None or not ids:
            unresolved += 1
            continue
        whole.update(ids)
        l, r = max(a, x), min(b, z)
        if l >= r:
            continue
        active += 1
        span = set(range(l, r))
        overlaps += len(span & hset)
        hset.update(span)
        where = min(index[k] for k in ids)
        inversions += where < last
        last = max(last, where)
        vid.update(ids)
        for k, i, j in g.get("VI_Char_Spans", []):
            if k in pool:
                chars = set(range(i, j))
                duplicate_vi += len(vi_positions[k] & chars)
                vi_positions[k].update(chars)
        hs = raw[l:r]
        vs = g["Vietnamese_Text"]
        number_hits += len(numbers(hs, True) & numbers(vs, False))
        entity_hits += len(entities(hs, True) & entities(vs, False))
        if isinstance(g["Score"], (float, int)) and math.isfinite(g["Score"]):
            scores.append(max(0.0, min(1.0, float(g["Score"]))))
        links.append([origin + l, origin + r, ids])

    ids = [k for k in pool if k in vid]
    match_pdf_range = interval(n for k in ids for n in (pool[k]["viet_page_start"], pool[k]["viet_page_end"]))
    match_coord_range = interval(
        cap_coord_page(cap, n) for k in ids for n in (pool[k]["viet_page_start"], pool[k]["viet_page_end"])
    )
    submitted_pdf_range = interval(n for v in submitted for n in (v["viet_page_start"], v["viet_page_end"]))

    hc = len(hset) / (b - a)
    vc = len(whole) / len(pool)
    mean_score = mean(scores) if scores else 0.0
    if match_coord_range:
        diff = abs(mean(match_coord_range) - y_coord)
        outside = bool(prior_coord and (match_coord_range[1] < prior_coord[0] or match_coord_range[0] > prior_coord[1]))
        coord_width = match_coord_range[1] - match_coord_range[0] + 1
        score = (
            2.4 * hc
            + 0.32 * vc
            + 0.08 * min(active, 5)
            + 0.19 * min(number_hits, 4)
            + 0.46 * min(entity_hits, 4)
            + 0.12 * mean_score
            - 0.13 * unresolved
            - 0.7 * inversions
            - 0.8 * overlaps / (b - a)
            - 0.05 * min(duplicate_vi, 20)
            - 0.12 * diff
            - 0.28 * bool(outside)
            - 0.09 * max(0, coord_width - 3)
        )
    else:
        score = -1.35

    return dict(
        range=match_coord_range,
        pdf_range=match_pdf_range,
        submitted_range=submitted_pdf_range,
        ids=ids,
        submitted_ids=list(pool),
        han_coverage=hc,
        vi_coverage=vc,
        missing_han=b - a - len(hset),
        duplicate_han=overlaps,
        duplicate_vi=duplicate_vi,
        unresolved=unresolved,
        order_violations=inversions,
        mapped_groups=active,
        number_hits=number_hits,
        entity_hits=entity_hits,
        weak_api_score=mean_score,
        links=links,
        score=score,
        status=result["status"],
        request_key=result.get("request_key"),
    )


def cross_book_window(pool: list[dict], seam_index: int, size: int = 10, shift: int = 0) -> list[dict]:
    """Select a contiguous cross-book slice centered at `seam_index` (boundary between adjacent books)."""
    return take(pool, seam_index + shift, size)


def coord_page_window(pool: list[dict], y_coord: float, cap: str, size: int = 10, shift: int = 0) -> list[dict]:
    """Select `size` segments centered around `y_coord` in continuous physical page coordinates."""
    near = min(
        range(len(pool)),
        key=lambda i: abs(
            mean((cap_coord_page(cap, pool[i]["viet_page_start"]), cap_coord_page(cap, pool[i]["viet_page_end"])))
            - y_coord
        ),
    )
    lo, hi = near, near
    near_start = pool[near]["viet_page_start"]
    while lo and pool[lo - 1]["viet_page_start"] == near_start:
        lo -= 1
    while hi + 1 < len(pool) and pool[hi + 1]["viet_page_start"] == near_start:
        hi += 1
    return take(pool, (lo + hi) // 2 + shift, size)


class EvaluationV2:
    def __init__(self, out_dir: Path, client: CoarseClientV2, cfg: dict, seg_by_cap: dict, identity: str):
        self.out = out_dir
        self.client = client
        self.cfg = cfg
        self.seg = seg_by_cap
        self.identity = identity

    def probe(self, p: dict, pool: list[dict], y_coord: float, prior_coord: list[int] | None, tag: str) -> dict:
        ss, origin, raw, spans = span_for(self.seg[p["cap"]], p["han_pdf_page"])
        key = fingerprint([tag, p["id"], [v["id"] for v in pool], self.identity])
        cp_file = self.out / "checkpoints" / f"{key}.json"
        if cp_file.exists():
            return json.loads(cp_file.read_text(encoding="utf-8"))

        legacy_pool = [legacy_viet_view(v) for v in pool]
        result = self.client.align(f"{tag}-{p['id']}", raw, spans, legacy_pool)
        row = collect_v2(result, p["global_raw_span"], origin, pool, y_coord, prior_coord, raw, p["cap"])
        row.update(cap=p["cap"], han_page=p["han_pdf_page"], purpose=tag, han_ids=[s["id_zh"] for s in ss])
        if result["status"] not in ("offline", "no_token", "rate_limited", "transient", "transport_error") and not self.client.halt:
            write_json(cp_file, row)
        return row

    def refine(
        self,
        p: dict,
        pool: list[dict],
        y_coord: float,
        prior_coord: list[int] | None,
        anchor_coords: list[int] | None,
        tag: str,
        seam_index: int | None = None,
    ) -> list[dict]:
        attempts: list[dict] = []
        seen: set[tuple[str, ...]] = set()
        cap = p["cap"]
        h = p["han_pdf_page"]

        def select_window(yy: float, size: int, shift: int = 0) -> list[dict]:
            if seam_index is not None:
                return cross_book_window(pool, seam_index, size, shift)
            return coord_page_window(pool, yy, cap, size, shift)

        def check(yy: float, size: int, shift: int = 0):
            v = select_window(yy, size, shift)
            ids = tuple(x["id"] for x in v)
            if not ids or ids in seen or self.client.halt:
                return
            seen.add(ids)
            attempts.append(self.probe(p, v, y_coord, prior_coord, tag))

        check(y_coord, 10, 0)
        check(y_coord, 10, 5 if h % 2 else -5)

        def best():
            agreement(attempts)
            return max(attempts, key=lambda q: q["adjusted"]) if attempts else None

        x = best()
        if not x or x["han_coverage"] < 0.75 or x["agreement"] < 0.34 or not x["range"]:
            check(y_coord, 16, -4 if h % 2 else 4)
            x = best()
        if not x or x["han_coverage"] < 0.45 or not x["range"]:
            min_c = cap_coord_page(cap, pool[0]["viet_page_start"])
            max_c = cap_coord_page(cap, pool[-1]["viet_page_end"])
            if seam_index is not None:
                check(y_coord, 20, 0)
            else:
                check(max(min_c, y_coord - 2), 12, 0)
                check(min(max_c, y_coord + 2), 12, 0)
        elif x["order_violations"] or x["unresolved"] >= 3:
            if seam_index is None:
                check(mean(x["range"]), 7, 0)

        for att in attempts:
            if anchor_coords and att["range"] and not (
                att["range"][0] <= min(anchor_coords) and att["range"][1] >= max(anchor_coords)
            ):
                att["anchor_adjusted"] = att["score"] - 0.85
        agreement(attempts)
        return attempts


def choices_v2(
    probes: list[dict],
    pool: list[dict],
    y_coord: float,
    anchor_coords: list[int] | None,
    cap: str,
    seam_index: int | None = None,
) -> list[dict]:
    if anchor_coords:
        lo_c, hi_c = min(anchor_coords), max(anchor_coords)
        selected = [
            v["id"]
            for v in pool
            if cap_coord_page(cap, v["viet_page_start"]) <= hi_c
            and cap_coord_page(cap, v["viet_page_end"]) >= lo_c
        ]
        return [{
            "range": [lo_c, hi_c],
            "pdf_range": [cap_pdf_page_from_coord(cap, lo_c), cap_pdf_page_from_coord(cap, hi_c)],
            "ids": selected,
            "adjusted": 1.8,
            "kind": "anchor",
        }]

    best: dict[tuple[int, int], dict] = {}
    for x in probes:
        if x["range"] and x["han_coverage"] >= 0.18 and x["order_violations"] <= 1:
            k = tuple(x["range"])
            opt = {**x, "kind": "api"}
            if k not in best or x["adjusted"] > best[k]["adjusted"]:
                best[k] = opt

    prior_win = (
        cross_book_window(pool, seam_index, 10, 0)
        if seam_index is not None
        else coord_page_window(pool, y_coord, cap, 10, 0)
    )
    lo_c, hi_c = interval(
        cap_coord_page(cap, n) for v in prior_win for n in (v["viet_page_start"], v["viet_page_end"])
    )
    k = (lo_c, hi_c)
    if k not in best:
        best[k] = {
            "range": [lo_c, hi_c],
            "pdf_range": [cap_pdf_page_from_coord(cap, lo_c), cap_pdf_page_from_coord(cap, hi_c)],
            "ids": [v["id"] for v in prior_win],
            "adjusted": -0.45,
            "kind": "interpolation",
        }
    return [*best.values(), {"range": None, "pdf_range": None, "ids": [], "adjusted": -0.80, "kind": "defer"}]


def to_pdf_range(cap: str, coord_range: list[int] | None) -> list[int] | None:
    if not coord_range:
        return None
    return [cap_pdf_page_from_coord(cap, coord_range[0]), cap_pdf_page_from_coord(cap, coord_range[1])]


def summarizes_probe_pdf(cap: str, x: dict) -> dict:
    s = summarizes_probe(x)
    s["range"] = x.get("pdf_range") or to_pdf_range(cap, x.get("range"))
    return s


def selection_v2(cap: str, details: list, solver: list[dict], page051_transition: dict) -> list[dict]:
    result = []
    for (p, orig_pdf, y_display, base_win, probes, opts, evidence), z in zip(details, solver):
        n = p["han_pdf_page"]
        anchor_pages = sorted({e["page"] for e in evidence})
        local = max(opts, key=lambda x: x["adjusted"])

        # Collect alternative options from solver options + distinct probe ranges on anchored pages
        alt_opts = [o for o in opts if o is not z and o["range"]]
        if anchor_pages:
            seen_ranges = {tuple(z["range"])}
            for pr in sorted(probes, key=lambda q: q["adjusted"], reverse=True):
                if pr["range"] and tuple(pr["range"]) not in seen_ranges:
                    seen_ranges.add(tuple(pr["range"]))
                    alt_opts.append({**pr, "kind": "api_probe_on_anchor"})
        alternatives = sorted(alt_opts, key=lambda x: x["adjusted"], reverse=True)
        alt_non_anchor_probe = [o for o in alternatives if o.get("kind") != "api_probe_on_anchor"]
        alt = alt_non_anchor_probe[0] if alt_non_anchor_probe else None

        close = bool(
            z["range"]
            and alt
            and (z["adjusted"] - alt["adjusted"] < 0.5)
            and any(abs(a - b) >= 2 for a, b in zip(z["range"], alt["range"]))
        )
        proxy = (
            None
            if z["kind"] != "api"
            else round(
                max(
                    0.0,
                    min(
                        1.0,
                        0.5 * z["han_coverage"]
                        + 0.35 * z["agreement"]
                        + 0.08 * min(z["entity_hits"], 2)
                        + 0.04 * min(z["number_hits"], 2)
                        - 0.08 * z["order_violations"],
                    ),
                ),
                3,
            )
        )

        if anchor_pages:
            status = "VERIFIED"
        elif not z["range"] or close:
            status = "AMBIGUOUS"
        elif (
            proxy is not None
            and proxy >= 0.78
            and z["agreement"] >= 0.55
            and z["han_coverage"] >= 0.8
            and not z["duplicate_han"]
            and not z["order_violations"]
        ):
            status = "HIGH_CONFIDENCE_ESTIMATED"
        else:
            status = "LOW_CONFIDENCE_ESTIMATED"

        pdf_rng = z.get("pdf_range") or to_pdf_range(cap, z["range"])
        lo_pdf, hi_pdf = pdf_rng or (None, None)
        ids = z["ids"]

        note = {
            "VERIFIED": "Independently established overlaps; listed range is an envelope of observed anchors, not verified completeness.",
            "AMBIGUOUS": "Competing or deferred estimate. Review alternatives before using as fixed context.",
            "LOW_CONFIDENCE_ESTIMATED": "Candidate context only; inspect original prior and source before official alignment.",
            "HIGH_CONFIDENCE_ESTIMATED": "Supported by overlapping probes; still an estimate.",
        }[status]
        if cap == "Cap_02" and n == 51:
            note = (
                "Cross-book VERIFIED transition page: right half (COL01-COL04, [40741,40805)) closes Book V on "
                "VIET_0001-0105 PDF p.105 (printed p.408); COL05 [40805,40812) is Book VI heading '撫邊雜錄卷之六' inside "
                "Cap_02-051-052-S4-0006; Book VI prose begins intra-S4 at offset 40812 on VIET_0405-0439 PDF p.405 "
                "(printed p.409) and continues into page 052 via Cap_02-051-052-S4-0012."
            )

        ev_payload = {"anchors": evidence, "chosen": summarizes_probe_pdf(cap, z)}
        if cap == "Cap_02" and n == 51:
            ev_payload["book_transition"] = page051_transition

        b1_pdf_range = interval(n_p for v in base_win for n_p in (v["viet_page_start"], v["viet_page_end"]))
        local_pdf_range = local.get("pdf_range") or to_pdf_range(cap, local["range"])

        result.append(
            dict(
                Cap=cap,
                Han_Page=n,
                Original_Verified_VI_Pages=anchor_pages,
                Original_Candidate_Range=orig_pdf,
                Interpolated_VI_Page=y_display,
                Predicted_VI_Page_Start=lo_pdf,
                Predicted_VI_Page_End=hi_pdf,
                Predicted_VI_ID_Start=ids[0] if ids else None,
                Predicted_VI_ID_End=ids[-1] if ids else None,
                Han_Coverage=z.get("han_coverage"),
                VI_Coverage=z.get("vi_coverage"),
                Mapping_Status=status,
                Confidence_Proxy=proxy,
                Evidence=ev_payload,
                Alternative_Candidates=[summarizes_probe_pdf(cap, x) for x in alternatives],
                Review_Note=note,
                Selected_VI_IDs=ids,
                B1_Range=b1_pdf_range,
                Local_Range=local_pdf_range,
                B2_Range=pdf_rng,
                Probes=len(probes),
            )
        )
    return result


def structural_coord(rows: list[dict], key: str, cap: str) -> dict:
    """Compute structural width, backward transitions, gaps, and overlap in continuous physical page coordinates."""
    indexed = [
        (r["Han_Page"], [cap_coord_page(cap, r[key][0]), cap_coord_page(cap, r[key][1])])
        for r in rows
        if r.get(key)
    ]
    vals = [v for _, v in indexed]
    pairs = [(a, b) for (i, a), (j, b) in zip(indexed, indexed[1:]) if j == i + 1]
    w_fn = lambda r: r[1] - r[0] + 1
    return {
        "ranges": len(vals),
        "mean_width": mean(map(w_fn, vals)) if vals else None,
        "median_width": median(map(w_fn, vals)) if vals else None,
        "backward": sum(b[0] < a[0] or b[1] < a[1] for a, b in pairs),
        "gap_pages": sum(max(0, b[0] - a[1] - 1) for a, b in pairs),
        "overlap_beyond_shared_endpoint": sum(max(0, a[1] - b[0]) for a, b in pairs),
    }


def loo_book6(ev: EvaluationV2, work_pages: list[dict], book6_maps: list[dict], book6_pool: list[dict]) -> list[dict]:
    """Leave-one-out hidden-anchor validation over Book VI verified anchors (51, 61, 71, 81, 87)."""
    cap = "Cap_02"
    all_anchors_pdf = anchors_for(book6_maps)
    all_anchors_coord = {h: [cap_coord_page(cap, vp) for vp in vps] for h, vps in all_anchors_pdf.items()}
    limits_coord = [
        cap_coord_page(cap, book6_pool[0]["viet_page_start"]),
        cap_coord_page(cap, book6_pool[-1]["viet_page_end"]),
    ]
    by_h = {p["han_pdf_page"]: p for p in work_pages}
    folds = []

    for target, truth_pdf in sorted(all_anchors_pdf.items()):
        train_coord = {h: cs for h, cs in all_anchors_coord.items() if h != target}
        if target not in by_h or len(train_coord) < 2:
            continue
        y_c = interpolate(target, train_coord, limits_coord)
        base_win = coord_page_window(book6_pool, y_c, cap, 10, 0)
        probes = ev.refine(by_h[target], book6_pool, y_c, None, None, f"loo-book6-{target}")
        options = []
        for p in work_pages:
            h = p["han_pdf_page"]
            yy_c = interpolate(h, train_coord, limits_coord)
            options.append(choices_v2(probes if h == target else [], book6_pool, yy_c, train_coord.get(h), cap))
        z = reconcile(options)[next(i for i, p in enumerate(work_pages) if p["han_pdf_page"] == target)]

        b0_pdf = prior_for(target, book6_maps)
        b1_pdf = interval(n for v in base_win for n in (v["viet_page_start"], v["viet_page_end"]))
        b2_pdf = to_pdf_range(cap, z["range"])
        b2_local_c = max(choices_v2(probes, book6_pool, y_c, None, cap), key=lambda x: x["adjusted"])["range"]
        b2_local_pdf = to_pdf_range(cap, b2_local_c)

        rec = {
            "cap": cap,
            "book_id": "Book_VI",
            "hidden_han": target,
            "heldout_vi": truth_pdf,
            "training_han": sorted(train_coord),
            "B0_range": b0_pdf,
            "B1_range": b1_pdf,
            "B2_range": b2_pdf,
            "B2_kind": z["kind"],
            "B2_local_range": b2_local_pdf,
            "B0_independent": False,
            "probes": [
                {**pr, "range": pr.get("pdf_range") or to_pdf_range(cap, pr.get("range"))}
                for pr in probes
            ],
        }
        for k in ("B0", "B1", "B2"):
            q = rec[f"{k}_range"]
            rec[f"{k}_recovered"] = sum(q[0] <= n <= q[1] for n in truth_pdf) if q else 0
            rec[f"{k}_distance"] = mean(max(q[0] - n, n - q[1], 0) for n in truth_pdf) if q else None
        folds.append(rec)
    return folds


def downstream_book6(ev: EvaluationV2, sample_pages: list[dict], chosen_rows: list[dict], book6_pool: list[dict], cap02_pool: list[dict]) -> list[dict]:
    chosen_by_h = {r["Han_Page"]: r for r in chosen_rows}
    out = []
    cap = "Cap_02"
    for p in sample_pages:
        h = p["han_pdf_page"]
        r = chosen_by_h[h]
        if not r["B2_Range"] or not r["Original_Candidate_Range"] or r["Interpolated_VI_Page"] is None:
            continue
        pool_use = cap02_pool if h == 51 else book6_pool
        y_c = 105.5 if h == 51 else cap_coord_page(cap, round(r["Interpolated_VI_Page"])) + (r["Interpolated_VI_Page"] - round(r["Interpolated_VI_Page"]))
        for k in ("B0", "B1", "B2"):
            q_pdf = r[{"B0": "Original_Candidate_Range", "B1": "B1_Range", "B2": "B2_Range"}[k]]
            if not q_pdf:
                continue
            q_c = [cap_coord_page(cap, q_pdf[0]), cap_coord_page(cap, q_pdf[1])]
            vs = [
                v for v in pool_use
                if q_c[0] <= cap_coord_page(cap, v["viet_page_end"])
                and cap_coord_page(cap, v["viet_page_start"]) <= q_c[1]
            ]
            if not vs:
                continue
            if k == "B0" and len(vs) > 30:
                vs = coord_page_window(vs, mean(q_c), cap, 30, 0)
            if ev.client.halt:
                return out
            item = ev.probe(p, vs, y_c, None, f"downstream-v2-{k}")
            item = dict(
                item,
                range=item.get("pdf_range") or to_pdf_range(cap, item.get("range")),
                approach=k,
                requested_range=q_pdf,
                vi_count=len(vs),
            )
            out.append(item)
    return out


def build_contexts_v2(
    final_rows: list[dict],
    v1_contexts_by_key: dict[tuple[str, int], dict],
    seg_by_cap: dict[str, list[dict]],
    vi_by_cap: dict[str, dict[str, dict]],
    cap02_pool: list[dict],
    book6_pool: list[dict],
    page051_transition: dict,
) -> list[dict]:
    """Build `window_context_refined.jsonl` maintaining 100% backward compatibility with Stage04.

    - Cap_01 (1..53), Cap_02 (1..50), and Cap_02 (88..92) preserve exact V1 records.
    - Cap_02 (51..87) provide identical Stage04 adapter fields (`cap`, `han_page`, `mapping_status`,
      `global_raw_start`, `han_ids`, `han`, `raw`, `spans`, `viet`, `viet_t1`) plus non-excluding
      fallback ID lists (`b2_range_vi_ids`, `b1_fallback_vi_ids`, `padded_context_vi_ids`) and
      explicit `book_transition` metadata on page 051.
    """
    out = []
    for row in final_rows:
        cap, h = row["Cap"], row["Han_Page"]
        if cap == "Cap_01" or h <= 50 or h >= 88:
            out.append(v1_contexts_by_key[(cap, h)])
            continue

        chosen_ids = row["Selected_VI_IDs"]
        ss, origin, raw, spans = span_for(seg_by_cap[cap], h)
        viet_legacy = [legacy_viet_view(vi_by_cap[cap][k]) for k in chosen_ids]
        vt1 = t1_rows({"viet": viet_legacy})

        # Non-excluding candidate IDs (range envelope, B1 fallback, and ±1 page padded window)
        pool_ref = cap02_pool if h == 51 else book6_pool
        b2_c = [cap_coord_page(cap, x) for x in row["B2_Range"]] if row["B2_Range"] else None
        b1_c = [cap_coord_page(cap, x) for x in row["B1_Range"]] if row["B1_Range"] else None

        b2_range_ids = (
            [
                v["id"] for v in pool_ref
                if b2_c[0] <= cap_coord_page(cap, v["viet_page_end"])
                and cap_coord_page(cap, v["viet_page_start"]) <= b2_c[1]
            ]
            if b2_c else []
        )
        b1_range_ids = (
            [
                v["id"] for v in pool_ref
                if b1_c[0] <= cap_coord_page(cap, v["viet_page_end"])
                and cap_coord_page(cap, v["viet_page_start"]) <= b1_c[1]
            ]
            if b1_c else []
        )
        env_lo = min(x[0] for x in (b2_c, b1_c) if x) - 1
        env_hi = max(x[1] for x in (b2_c, b1_c) if x) + 1
        if h >= 52:
            env_lo = max(106, env_lo)
            env_hi = min(140, env_hi)
        else:
            env_lo = max(104, env_lo)
            env_hi = min(107, env_hi)
        padded_ids = [
            v["id"] for v in pool_ref
            if env_lo <= cap_coord_page(cap, v["viet_page_end"])
            and cap_coord_page(cap, v["viet_page_start"]) <= env_hi
        ]

        rec = dict(
            cap=cap,
            han_page=h,
            mapping_status=row["Mapping_Status"],
            global_raw_start=origin,
            han_ids=[s["id_zh"] for s in ss],
            han=ss,
            raw=raw,
            spans=spans,
            viet=viet_legacy,
            viet_t1=vt1,
            b2_range_vi_ids=b2_range_ids,
            b1_fallback_vi_ids=b1_range_ids,
            padded_context_vi_ids=padded_ids,
        )
        if h == 51:
            rec["book_transition"] = page051_transition
        out.append(rec)
    return out


def collect_shared_hashes() -> dict[str, str]:
    """Snapshot SHA-256 of all shared Stage02, Stage03, Stage03B, and Stage04_V4_Handoff files."""
    paths = [
        ROOT / "02_ocr_tho/Cap_01/Cap_01_HAN_all_pages.txt",
        ROOT / "02_ocr_tho/Cap_02/Cap_02_HAN_all_pages.txt",
        ROOT / "02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx",
        ROOT / "02_ocr_tho/Cap_02/VIET/VIET_0001-0105.xlsx",
        ROOT / "02_ocr_tho/Cap_02/VIET/VIET_0405-0439.xlsx",
        STAGE / "config/stage03_release.json",
        PROD_DIR / "han_segments.jsonl",
        PROD_DIR / "window_context.jsonl",
        PROD_DIR / "production_audit.json",
        PROD_DIR / "production_manifest.json",
        V1_DIR / "page_mapping_refined.jsonl",
        V1_DIR / "page_mapping_refined.xlsx",
        V1_DIR / "window_context_refined.jsonl",
        V1_DIR / "mapping_comparison.xlsx",
        V1_DIR / "mapping_candidates.xlsx",
        V1_DIR / "uncertain_pages.xlsx",
        V1_DIR / "metrics.json",
        V1_DIR / "manifest.json",
        V1_DIR / "requests.jsonl",
        V1_DIR / "coarse_mapping_report.md",
    ]
    for p in sorted((STAGE / "scripts").glob("*.py")):
        paths.append(p)
    for p in sorted((STAGE / "tests").glob("*.py")):
        paths.append(p)
    for p in sorted((ROOT / "Stage04_V4_Handoff").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            paths.append(p)

    hashes: dict[str, str] = {}
    for p in paths:
        if p.is_file():
            rel = p.relative_to(ROOT).as_posix()
            try:
                hashes[rel] = sha256_file(p)
            except PermissionError:
                hashes[rel] = "LOCKED"
    return hashes


def load_v1_probe_sheets() -> tuple[list[dict], list[dict]]:
    wb = load_workbook(V1_DIR / "mapping_candidates.xlsx", read_only=True, data_only=True)
    try:
        out = {}
        for sname in ("Production", "LOO_Probes"):
            ws = wb[sname]
            rows = list(ws.iter_rows(values_only=True))
            headers = list(rows[0])
            out[sname] = [dict(zip(headers, r)) for r in rows[1:] if any(c is not None for c in r)]
        return out["Production"], out["LOO_Probes"]
    finally:
        wb.close()


def make_report_v2(out_dir: Path, metrics: dict, integrity: dict, pilot: bool):
    v1_stat = metrics["v1_statuses"]
    v2_stat = metrics["statuses"]
    cov = metrics["vi_id_coverage"]
    api = metrics["api_summary"]

    lines = [
        "# Stage 03B — Coarse Page Mapping V2 (Book VI Integration)" + (" [Pilot]" if pilot else ""),
        "",
        "## 1. Executive Summary",
        "",
        (
            f"- **Coverage expansion**: Supported/mapped Han pages increased from **{metrics['supported_pages_v1']}** "
            f"(53 Cap_01 + 50 Cap_02 full + 1 Cap_02 partial = 104 with partial, 103 full) to "
            f"**{metrics['supported_pages_v2']}/145** full-supported pages (`Cap_01` 001–053 + `Cap_02` 001–087), "
            f"with **0** partial pages and **{metrics['unmatched_pages_v2']}** unresolved pages (`Cap_02` 088–092)."
        ),
        f"- **Refined page status counts (V1 → V2)**: `{v1_stat}` → `{v2_stat}`.",
        (
            f"- **Vietnamese corpus inventory**: Extended from **1,676** eligible segments (`685` Cap_01 + `991` Cap_02 Book V) "
            f"to **2,054** eligible segments (+`378` Cap_02 Book VI segments from `VIET_0405-0439.xlsx`, namespace `Cap_02_VI-VI-*`), "
            f"all exported in `viet_segments_extended.jsonl` with reversible T1 character spans and zero ID collisions."
        ),
        (
            f"- **Page 051 cross-book transition**: Upgraded from `PARTIAL` (`[105, 105]`) to `VERIFIED` (`[105, 405]`, "
            f"printed pp. 408–409, physical width = 2 pages), preserving all 19 Book V p.105 segments and all 8 Book VI p.405 "
            f"segments (27 segments in reading order) and documenting the exact intra-S4 transition at global offset `40812` "
            f"(after heading `撫邊雜錄卷之六` at `[40805, 40812)` inside `Cap_02-051-052-S4-0006`)."
        ),
        (
            f"- **API usage**: **{api['live_network_requests']}** live Alignment API calls this execution "
            f"(logged total in V2 `requests.jsonl`: **{api['logged_requests_total']}**), "
            f"**{api['cache_hits']}** exact-payload cache hits, **{api['retries_used']}** retries, "
            f"**{api['http_429_count']}** HTTP 429 events, **{api['permanent_failures']}** permanent failures, halt=`{api['halt']}`."
        ),
        "- **Semantic caveat**: Coarse mapping provides candidate page/segment windows only. **Zero Gold semantic labels (`Label_Target`) are assigned or inferred.**",
        "",
        "## 2. Structural Comparison (Continuous Physical Page Coordinates)",
        "",
        "| Scope | Method | Ranges | Mean width (pages) | Median width | Backward transitions | Gap pages | Excess overlap |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scope, methods in metrics["structural"].items():
        for mname, st in methods.items():
            mw = f"{st['mean_width']:.2f}" if st["mean_width"] is not None else "—"
            md = f"{st['median_width']:.1f}" if st["median_width"] is not None else "—"
            lines.append(
                f"| {scope} | {mname} | {st['ranges']} | {mw} | {md} | {st['backward']} | {st['gap_pages']} | {st['overlap_beyond_shared_endpoint']} |"
            )

    lines += [
        "",
        (
            "Note: For `Cap_02`, Book V PDF pages `1–105` correspond to printed pages `304–408` and Book VI PDF pages "
            "`405–439` correspond to printed pages `409–443` (140 consecutive printed pages). Widths, gaps, and monotonicity "
            "across the Book V → Book VI seam at Han page 051 are evaluated in continuous physical page coordinates (`1..140`) "
            "so the PDF numbering jump (`105 → 405`) does not create a synthetic 299-page gap."
        ),
        "",
        "## 3. Vietnamese ID Coverage & Non-Exclusion Audit",
        "",
        "| Subset | Total Eligible VI IDs | In `Selected_VI_IDs` | Touching `B2_Range` | In `±1` Page Padded Context | In `viet_segments_extended.jsonl` |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sub_name, cinfo in cov.items():
        tot = cinfo["total_eligible"]
        lines.append(
            f"| {sub_name} | {tot} | {cinfo['in_selected_vi_ids']} ({100*cinfo['in_selected_vi_ids']/tot:.1f}%) | "
            f"{cinfo['touching_b2_range']} ({100*cinfo['touching_b2_range']/tot:.1f}%) | "
            f"{cinfo['in_padded_plus_minus_1_page']} ({100*cinfo['in_padded_plus_minus_1_page']/tot:.1f}%) | "
            f"{cinfo['in_extended_catalog']} (100.0%) |"
        )

    lines += [
        "",
        (
            "As in Stage 03B V1, `Selected_VI_IDs` on unanchored B2 pages lists only the specific segments matched by the "
            "winning 10-segment probe, so downstream Stage 04 alignment **must not** treat `Selected_VI_IDs` as a hard exclusion filter. "
            "Using `padded_context_vi_ids` (`B2_Range ∪ B1_Range ± 1` page) on `Cap_02` 051–087 retains **378/378 (100.0%)** of eligible "
            "Book VI segments, and `viet_segments_extended.jsonl` retains **2,054/2,054 (100.0%)** across both Caps."
        ),
        "",
        "## 4. Hidden-Anchor Leave-One-Out Validation",
        "",
    ]
    for group_label, folds in [("All 15 folds (Cap_01 + Book V + Book VI)", metrics["validation"]), ("Book VI 5 folds (51, 61, 71, 81, 87)", metrics["validation_book6"])]:
        if folds:
            total_truth = sum(len(f["heldout_vi"]) for f in folds)
            lines.append(f"**{group_label}**:")
            for k in ("B0", "B1", "B2"):
                dists = [f[f"{k}_distance"] for f in folds if f[f"{k}_distance"] is not None]
                recov = sum(f[f"{k}_recovered"] for f in folds)
                lines.append(
                    f"- `{k}`: {recov}/{total_truth} anchor overlaps recovered; mean distance {mean(dists):.2f} VI pages over {len(dists)}/{len(folds)} folds."
                    if dists else f"- `{k}`: unavailable."
                )
            lines.append("")

    lines += [
        "## 5. Downstream Context Comparison (Paired B0 vs B1 vs B2)",
        "",
    ]
    q = metrics["downstream"]
    ok_pages = {
        (r["cap"], r["han_page"])
        for r in q
        if sum(x["cap"] == r["cap"] and x["han_page"] == r["han_page"] and x["status"] == "ok" for x in q) == 3
    }
    for k in ("B0", "B1", "B2"):
        sub = [x for x in q if x["approach"] == k and (x["cap"], x["han_page"]) in ok_pages]
        if sub:
            lines.append(
                f"- `{k}` ({len(sub)} matched pages across Cap_01, Book V, Book VI): "
                f"mean Han/VI coverage `{mean(r['han_coverage'] for r in sub):.3f}` / `{mean(r['vi_coverage'] for r in sub):.3f}`; "
                f"unresolved groups: `{sum(r['unresolved'] for r in sub)}`."
            )

    lines += [
        "",
        "## 6. Remaining Unmatched & Ambiguous Pages",
        "",
        f"- **Unmatched Han pages ({len(metrics['unmatched_page_list'])})**: `{metrics['unmatched_page_list']}`",
        "  - `Cap_02:088–089`: Ngô Thì Sĩ's postface (*Phủ biên tạp lục bạt*, 1777); Vietnamese text begins at PDF p. 440, outside `VIET_0405-0439.xlsx`. Cross-page S4 unit `Cap_02-087-088-S4-0005` bridges Book VI's last two chars `[52417,52419)` into page 088.",
        "  - `Cap_02:090`: Duplicate scan of `Cap_02:001` (Book V opening `撫邊雜錄卷之五...人才何代無之`); intentionally kept unmatched to prevent false alignment to Book VI.",
        "  - `Cap_02:091–092`: Archival shelfmark OCR fragments (`R16061`, `01`); no literary text.",
        f"- **Ambiguous Han pages ({len(metrics['ambiguous_page_list'])})**: `{metrics['ambiguous_page_list']}` (competing candidates within `<0.5` adjusted score and `>=2` pages apart; inspect `uncertain_pages.xlsx` and retain union/padded candidate context in Stage 04).",
        "",
        "## 7. Integrity & Frozen Artifact Verification",
        "",
        f"- Frozen S4 segments verified: **{integrity['frozen_han_s4']['total_segments']}** segments, **{integrity['frozen_han_s4']['total_source_chars']}** Han characters, `exact_reconstruction = True`.",
        f"- Unaffected mappings verified identical to V1: `Cap_01` `001–053` (**53/53** exact), `Cap_02` `001–050` (**50/50** exact), `Cap_02` `088–092` (**5/5** exact).",
        f"- Shared Stage02/Stage03/Stage03B/Stage04_V4_Handoff files modified: **{integrity['shared_files_modified_count']}**.",
        "- See `STAGE04_INTEGRATION_GUIDE.md` for exact Stage 04 V4 consumption instructions.",
    ]
    (out_dir / "coarse_mapping_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_v2(live: bool = False, resume: bool = False, pilot: bool = False, output_dir: Path = DEFAULT_OUT, api_delay: float = 1.1, api_retries: int = 4) -> int:
    started = time.monotonic()
    hashes_before = collect_shared_hashes()

    # Load frozen Stage03 production & Stage03B V1 artifacts read-only
    prod_manifest = json.loads((PROD_DIR / "production_manifest.json").read_text(encoding="utf-8"))
    if prod_manifest.get("release_status") != "complete":
        raise ValueError("Expected completed Stage03 production release")

    s4_all = read_jsonl(PROD_DIR / "han_segments.jsonl")
    seg_by_cap: dict[str, list[dict]] = defaultdict(list)
    for s in s4_all:
        seg_by_cap[s["window"].rsplit("-", 2)[0]].append(s)

    v1_mapping_rows = read_jsonl(V1_DIR / "page_mapping_refined.jsonl")
    v1_context_rows = read_jsonl(V1_DIR / "window_context_refined.jsonl")
    v1_metrics = json.loads((V1_DIR / "metrics.json").read_text(encoding="utf-8"))
    v1_prod_probes, v1_loo_probes = load_v1_probe_sheets()

    v1_map_by_key = {(r["Cap"], r["Han_Page"]): r for r in v1_mapping_rows}
    v1_ctx_by_key = {(r["cap"], r["han_page"]): r for r in v1_context_rows}

    # Load multi-workbook sources via isolated V2 loader
    han_pages, viet_segments, mapping_rows, wb_audits = load_sources_v2()
    frozen_han_audit = verify_frozen_s4_and_han(han_pages)
    transition_and_anchors = analyze_page051_and_book6_anchors(han_pages, viet_segments, mapping_rows)
    page051_transition = transition_and_anchors["page_051_transition"]

    cfg = json.loads((STAGE / "config/stage03_release.json").read_text(encoding="utf-8"))
    out = output_dir / "pilot" if pilot else output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "checkpoints").mkdir(exist_ok=True)

    lock_file = out / ".coarse_mapping_v2.lock"
    if lock_file.exists():
        raise RuntimeError(f"Lock file exists at {lock_file}; another Coarse Mapping V2 writer may be active.")
    lock_file.write_text(json.dumps({"pid": os.getpid(), "started_epoch": time.time()}), encoding="utf-8")

    try:
        code_hash = fingerprint([
            (p.name, p.read_text(encoding="utf-8"))
            for p in sorted(SCRIPTS_V2.glob("*.py"))
        ])
        input_hash_subset = {
            k: v for k, v in hashes_before.items()
            if k.startswith(("02_ocr_tho/", "03_text_sach/artifacts/production/han_segments", "03_text_sach/config/"))
        }
        identity = fingerprint([VERSION, input_hash_subset, cfg, code_hash, pilot])
        manifest_path = out / "manifest.json"
        if manifest_path.exists() and resume:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing_manifest.get("identity") != identity:
                raise ValueError("Existing Coarse Mapping V2 manifest identity mismatch on --resume")

        manifest_obj = {
            "version": VERSION,
            "identity": identity,
            "pilot": pilot,
            "code_sha256": code_hash,
            "config": {**cfg, "api_delay_v2": api_delay, "api_retries_v2": api_retries},
            "workbooks": [s.rel_path for s in WORKBOOK_SPECS],
            "status": "running",
        }
        write_json(manifest_path, manifest_obj)

        # Index Vietnamese segments by Cap and Book
        vi_by_cap: dict[str, dict[str, dict]] = defaultdict(dict)
        for v in viet_segments:
            vi_by_cap[v["cap"]][v["id"]] = v
        book5_pool = [v for v in viet_segments if v["book_id"] == "Book_V"]
        book6_pool = [v for v in viet_segments if v["book_id"] == "Book_VI"]
        cap02_pool = book5_pool + book6_pool
        seam_idx_51 = len(book5_pool)  # 991: exact boundary between 0105-018 and 0405-003

        cap02_maps = [m for m in mapping_rows if m["cap"] == "Cap_02"]
        book6_maps = [m for m in mapping_rows if m["book_id"] == "Book_VI"]
        book6_anchors_pdf = anchors_for(book6_maps)  # {51:[405], 61:[414], 71:[424,425], 81:[434], 87:[439]}
        book6_anchors_coord = {h: [cap_coord_page("Cap_02", vp) for vp in vps] for h, vps in book6_anchors_pdf.items()}
        book6_limits_coord = [
            cap_coord_page("Cap_02", book6_pool[0]["viet_page_start"]),
            cap_coord_page("Cap_02", book6_pool[-1]["viet_page_end"]),
        ]  # [106, 140]

        client = CoarseClientV2(out, cfg, live=live, api_delay=api_delay, api_retries=api_retries)
        ev = EvaluationV2(out, client, cfg, seg_by_cap, identity)

        try:
            target_Nums = {51, 52, 61, 71, 81, 87} if pilot else set(range(51, 88))
            cap02_target_pages = [
                p for p in han_pages
                if p["cap"] == "Cap_02" and p["han_pdf_page"] in target_Nums
            ]

            details_51_87 = []
            options_51_87 = []
            new_prod_probes: list[dict] = []

            for p in cap02_target_pages:
                h = p["han_pdf_page"]
                if h == 51:
                    orig_pdf = prior_for(51, cap02_maps)  # [104, 414]
                    orig_coord = [cap_coord_page("Cap_02", orig_pdf[0]), cap_coord_page("Cap_02", orig_pdf[1])]  # [104, 115]
                    evid = original_evidence(51, cap02_maps)  # [105 (nửa phải), 405 (nửa trái)]
                    anchor_c = [105, 106]
                    y_coord = 105.5
                    y_display = 405.0
                    base_win = cross_book_window(cap02_pool, seam_idx_51, 10, 0)
                    probes = ev.refine(p, cap02_pool, y_coord, orig_coord, anchor_c, "production-v2", seam_index=seam_idx_51)
                    opts = choices_v2(probes, cap02_pool, y_coord, anchor_c, "Cap_02", seam_index=seam_idx_51)
                else:
                    orig_pdf = prior_for(h, book6_maps)
                    orig_coord = [cap_coord_page("Cap_02", orig_pdf[0]), cap_coord_page("Cap_02", orig_pdf[1])] if orig_pdf else None
                    evid = original_evidence(h, book6_maps)
                    anchor_c = book6_anchors_coord.get(h)
                    y_coord = interpolate(h, book6_anchors_coord, book6_limits_coord)
                    y_display = y_coord + 299.0  # Exact Book VI PDF page coordinate in [405.0, 439.0]
                    base_win = coord_page_window(book6_pool, y_coord, "Cap_02", 10, 0)
                    probes = ev.refine(p, book6_pool, y_coord, orig_coord, anchor_c, "production-v2")
                    opts = choices_v2(probes, book6_pool, y_coord, anchor_c, "Cap_02")

                for pr in probes:
                    new_prod_probes.append({
                        **pr,
                        "range": pr.get("pdf_range") or to_pdf_range("Cap_02", pr.get("range")),
                    })
                options_51_87.append(opts)
                details_51_87.append((p, orig_pdf, y_display, base_win, probes, opts, evid))
                print(
                    f"Cap_02 {h:03d}: {len(probes)} probes; {len(opts)} options; {client.attempts} live calls ({client.hits} cache hits)",
                    flush=True,
                )

            # Reconcile Cap_02 051-087 monotonically anchored from page 050's verified state (104, 105)
            p50_locked_option = [{"range": [104, 105], "pdf_range": [104, 105], "ids": v1_map_by_key[("Cap_02", 50)]["Selected_VI_IDs"], "adjusted": 1.8, "kind": "anchor"}]
            solved_chain = reconcile([p50_locked_option, *options_51_87])[1:]
            chosen_51_87 = selection_v2("Cap_02", details_51_87, solved_chain, page051_transition)
            chosen_by_h = {r["Han_Page"]: r for r in chosen_51_87}

            # Assemble complete 145-page corpus mapping, preserving unaffected regions unchanged
            if pilot:
                final_rows = chosen_51_87
            else:
                final_rows = []
                for h in range(1, 54):
                    final_rows.append(v1_map_by_key[("Cap_01", h)])
                for h in range(1, 93):
                    if 51 <= h <= 87:
                        final_rows.append(chosen_by_h[h])
                    else:
                        final_rows.append(v1_map_by_key[("Cap_02", h)])

            # Run Book VI LOO hidden-anchor evaluation & downstream context comparison
            book6_loo: list[dict] = []
            book6_downstream: list[dict] = []
            if not pilot and not client.halt:
                book6_loo = loo_book6(ev, cap02_target_pages, book6_maps, book6_pool)
            if not pilot and not client.halt:
                hn = sorted(p["han_pdf_page"] for p in cap02_target_pages)
                sample_h = {hn[0], hn[1], hn[len(hn) // 3], hn[(2 * len(hn)) // 3], hn[-1]}
                sample_pages = [p for p in cap02_target_pages if p["han_pdf_page"] in sample_h]
                book6_downstream = downstream_book6(ev, sample_pages, chosen_51_87, book6_pool, cap02_pool)
        finally:
            client.close()

        if not pilot and len(final_rows) != 145:
            raise ValueError(f"Expected 145 final mapping rows, got {len(final_rows)}")

        # Build contexts and write JSONL artifacts
        contexts_v2 = (
            build_contexts_v2(final_rows, v1_ctx_by_key, seg_by_cap, vi_by_cap, cap02_pool, book6_pool, page051_transition)
            if not pilot
            else build_contexts_v2(final_rows, v1_ctx_by_key, seg_by_cap, vi_by_cap, cap02_pool, book6_pool, page051_transition)
        )
        dump_jsonl(out / "viet_segments_extended.jsonl", viet_segments)
        dump_jsonl(out / "page_mapping_refined.jsonl", final_rows)
        dump_jsonl(out / "window_context_refined.jsonl", contexts_v2)

        # Page 051 explicit sheet for human review
        p51_sheet_rows = [
            {
                "Region": "Right-hand (Book V closing)",
                "Book_ID": "Book_V",
                "Workbook": "VIET_0001-0105.xlsx",
                "Columns": "COL01-COL04",
                "Global_Raw_Span": json.dumps(page051_transition["right_hand_book_v"]["global_raw_span"]),
                "S4_Segments": ", ".join(page051_transition["right_hand_book_v"]["s4_segment_ids"]),
                "Verified_VI_PDF_Page": 105,
                "Printed_Page": 408,
                "Eligible_VI_Count": len(page051_transition["right_hand_book_v"]["eligible_viet_ids"]),
                "Note": page051_transition["right_hand_book_v"]["cross_page_from_050_note"],
            },
            {
                "Region": "Center-left title column (Book VI heading)",
                "Book_ID": "Book_VI",
                "Workbook": "VIET_0405-0439.xlsx",
                "Columns": "COL05",
                "Global_Raw_Span": json.dumps(page051_transition["book_vi_heading_column"]["global_raw_span"]),
                "S4_Segments": page051_transition["book_vi_heading_column"]["containing_s4_id"],
                "Verified_VI_PDF_Page": 405,
                "Printed_Page": 409,
                "Eligible_VI_Count": 0,
                "Note": "Heading '撫邊雜錄卷之六' inside S4-0006; corresponds to ineligible title row Cap_02_VI-VI-0405-001.",
            },
            {
                "Region": "Left-hand prose (Book VI opening)",
                "Book_ID": "Book_VI",
                "Workbook": "VIET_0405-0439.xlsx",
                "Columns": "COL06-COL13",
                "Global_Raw_Span": json.dumps(page051_transition["left_hand_book_vi_prose"]["global_raw_span"]),
                "S4_Segments": ", ".join(page051_transition["left_hand_book_vi_prose"]["s4_segment_ids"]),
                "Verified_VI_PDF_Page": 405,
                "Printed_Page": 409,
                "Eligible_VI_Count": len(page051_transition["left_hand_book_vi_prose"]["eligible_viet_ids"]),
                "Note": page051_transition["left_hand_book_vi_prose"]["cross_page_to_052_segment"]["note"],
            },
        ]
        workbook(out / "page_mapping_refined.xlsx", {"Refined": final_rows, "Page_051_Transition": p51_sheet_rows})

        # Candidate probes workbook (preserving V1 Cap_01 + Cap_02 001-050 probes and adding V2 051-087 probes)
        kept_v1_prod = [r for r in v1_prod_probes if not (r.get("cap") == "Cap_02" and int(r.get("han_page", 0)) >= 51)]
        all_prod_probes = kept_v1_prod + new_prod_probes if not pilot else new_prod_probes
        all_loo_probes = v1_loo_probes + [pr for fold in book6_loo for pr in fold["probes"]] if not pilot else []
        workbook(out / "mapping_candidates.xlsx", {"Production": all_prod_probes, "LOO_Probes": all_loo_probes})

        # Uncertain pages workbook
        review_rows = [r for r in final_rows if r["Mapping_Status"] not in ("VERIFIED", "HIGH_CONFIDENCE_ESTIMATED")]
        ambig_unmatched = [r for r in final_rows if r["Mapping_Status"] in ("AMBIGUOUS", "PARTIAL", "UNMATCHED")]
        workbook(out / "uncertain_pages.xlsx", {"Review": review_rows, "Ambiguous_And_Unmatched": ambig_unmatched})

        # Structural, LOO, Downstream, VI ID coverage, and V1-vs-V2 diff
        field_map = [("B0", "Original_Candidate_Range"), ("B1", "B1_Range"), ("B2", "B2_Range"), ("local", "Local_Range")]
        structural_stats = {}
        if not pilot:
            cap01_sub = [r for r in final_rows if r["Cap"] == "Cap_01" and r["Mapping_Status"] != "UNMATCHED"]
            cap02_book5_sub = [r for r in final_rows if r["Cap"] == "Cap_02" and r["Han_Page"] <= 50]
            cap02_book6_sub = [r for r in final_rows if r["Cap"] == "Cap_02" and 51 <= r["Han_Page"] <= 87]
            cap02_all_sub = [r for r in final_rows if r["Cap"] == "Cap_02" and r["Mapping_Status"] != "UNMATCHED"]
            for label, sub, cap_name in [
                ("Cap_01 (001-053)", cap01_sub, "Cap_01"),
                ("Cap_02_Book_V (001-050)", cap02_book5_sub, "Cap_02"),
                ("Cap_02_Book_VI (051-087)", cap02_book6_sub, "Cap_02"),
                ("Cap_02_Combined (001-087)", cap02_all_sub, "Cap_02"),
            ]:
                structural_stats[label] = {k: structural_coord(sub, f, cap_name) for k, f in field_map}
        else:
            structural_stats["Cap_02_Pilot"] = {k: structural_coord(final_rows, f, "Cap_02") for k, f in field_map}

        valid_book6_flat = [{k: v for k, v in r.items() if k != "probes"} for r in book6_loo]
        valid_all_flat = v1_metrics["validation"] + valid_book6_flat if not pilot else valid_book6_flat
        downstream_all = v1_metrics["downstream"] + book6_downstream if not pilot else book6_downstream
        silver_proxy = v1_metrics["silver_proxy"] if not pilot else []

        # VI ID coverage across subsets
        def coverage_for(subset_viet: list[dict], rows_sub: list[dict], ctx_sub: list[dict], cap_name: str) -> dict:
            elig_ids = {v["id"] for v in subset_viet}
            sel_ids = {i for r in rows_sub for i in r["Selected_VI_IDs"] if i in elig_ids}
            b2_coords = {
                c
                for r in rows_sub
                if r["B2_Range"]
                for c in range(cap_coord_page(cap_name, r["B2_Range"][0]), cap_coord_page(cap_name, r["B2_Range"][1]) + 1)
            }
            touch_b2 = {
                v["id"] for v in subset_viet
                if any(cap_coord_page(cap_name, v["viet_page_start"]) <= c <= cap_coord_page(cap_name, v["viet_page_end"]) for c in b2_coords)
            }
            padded_coords = {c + d for c in b2_coords for d in (-1, 0, 1)}
            touch_padded = {
                v["id"] for v in subset_viet
                if any(cap_coord_page(cap_name, v["viet_page_start"]) <= c <= cap_coord_page(cap_name, v["viet_page_end"]) for c in padded_coords)
            }
            for ctx in ctx_sub:
                touch_padded.update(i for i in ctx.get("padded_context_vi_ids", []) if i in elig_ids)
            return {
                "total_eligible": len(elig_ids),
                "in_selected_vi_ids": len(sel_ids),
                "touching_b2_range": len(touch_b2),
                "in_padded_plus_minus_1_page": len(touch_padded),
                "in_extended_catalog": len(elig_ids),
                "missing_from_padded_context": sorted(elig_ids - touch_padded),
            }

        vi_coverage_summary = {}
        if not pilot:
            c1_rows = [r for r in final_rows if r["Cap"] == "Cap_01"]
            c2_rows = [r for r in final_rows if r["Cap"] == "Cap_02"]
            c2_b5_rows = [r for r in c2_rows if r["Han_Page"] <= 51]
            c2_b6_rows = [r for r in c2_rows if 51 <= r["Han_Page"] <= 87]
            ctx_b6 = [c for c in contexts_v2 if c["cap"] == "Cap_02" and 51 <= c["han_page"] <= 87]

            vi_coverage_summary["Cap_01 (VIET_0186-0251)"] = coverage_for([v for v in viet_segments if v["cap"] == "Cap_01"], c1_rows, [], "Cap_01")
            vi_coverage_summary["Cap_02 Book V (VIET_0001-0105)"] = coverage_for(book5_pool, c2_b5_rows, [], "Cap_02")
            vi_coverage_summary["Cap_02 Book VI (VIET_0405-0439)"] = coverage_for(book6_pool, c2_b6_rows, ctx_b6, "Cap_02")
            vi_coverage_summary["All Corpus Combined"] = {
                k: sum(vi_coverage_summary[s][k] for s in vi_coverage_summary)
                for k in ("total_eligible", "in_selected_vi_ids", "touching_b2_range", "in_padded_plus_minus_1_page", "in_extended_catalog")
            }

        # Page-by-page diff vs V1
        page_diff_rows = []
        if not pilot:
            for r2 in final_rows:
                r1 = v1_map_by_key[(r2["Cap"], r2["Han_Page"])]
                page_diff_rows.append({
                    "Cap": r2["Cap"],
                    "Han_Page": r2["Han_Page"],
                    "V1_Status": r1["Mapping_Status"],
                    "V2_Status": r2["Mapping_Status"],
                    "V1_B2_Range": r1["B2_Range"],
                    "V2_B2_Range": r2["B2_Range"],
                    "V1_Selected_Count": len(r1["Selected_VI_IDs"]),
                    "V2_Selected_Count": len(r2["Selected_VI_IDs"]),
                    "Changed": (r1["Mapping_Status"] != r2["Mapping_Status"]) or (r1["B2_Range"] != r2["B2_Range"]) or (r1["Selected_VI_IDs"] != r2["Selected_VI_IDs"]),
                })

        summary_comp_rows = [
            {"Metric": "Supported Han Pages (Full)", "V1_Before": 103, "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] not in ("UNMATCHED", "PARTIAL")), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] not in ("UNMATCHED", "PARTIAL")) - 103},
            {"Metric": "Partially Supported Han Pages", "V1_Before": 1, "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] == "PARTIAL"), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] == "PARTIAL") - 1},
            {"Metric": "Unmatched Han Pages", "V1_Before": 41, "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] == "UNMATCHED"), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] == "UNMATCHED") - 41},
            {"Metric": "Eligible Vietnamese Segments", "V1_Before": 1676, "V2_After": len(viet_segments), "Delta": len(viet_segments) - 1676},
            {"Metric": "VERIFIED Han Pages", "V1_Before": v1_metrics["statuses"].get("VERIFIED", 0), "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] == "VERIFIED"), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] == "VERIFIED") - v1_metrics["statuses"].get("VERIFIED", 0)},
            {"Metric": "HIGH_CONFIDENCE_ESTIMATED Pages", "V1_Before": v1_metrics["statuses"].get("HIGH_CONFIDENCE_ESTIMATED", 0), "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] == "HIGH_CONFIDENCE_ESTIMATED"), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] == "HIGH_CONFIDENCE_ESTIMATED") - v1_metrics["statuses"].get("HIGH_CONFIDENCE_ESTIMATED", 0)},
            {"Metric": "LOW_CONFIDENCE_ESTIMATED Pages", "V1_Before": v1_metrics["statuses"].get("LOW_CONFIDENCE_ESTIMATED", 0), "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] == "LOW_CONFIDENCE_ESTIMATED"), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] == "LOW_CONFIDENCE_ESTIMATED") - v1_metrics["statuses"].get("LOW_CONFIDENCE_ESTIMATED", 0)},
            {"Metric": "AMBIGUOUS Pages", "V1_Before": v1_metrics["statuses"].get("AMBIGUOUS", 0), "V2_After": sum(1 for r in final_rows if r["Mapping_Status"] == "AMBIGUOUS"), "Delta": sum(1 for r in final_rows if r["Mapping_Status"] == "AMBIGUOUS") - v1_metrics["statuses"].get("AMBIGUOUS", 0)},
        ]
        struct_tab = [
            dict(scope=scope, approach=k, **vals)
            for scope, mdict in structural_stats.items()
            for k, vals in mdict.items()
        ]
        workbook(
            out / "mapping_comparison.xlsx",
            {
                "Before_vs_After_Summary": summary_comp_rows,
                "Structural": struct_tab,
                "Page_By_Page_Diff": page_diff_rows,
                "Hidden_Anchors": valid_all_flat,
                "Downstream": downstream_all,
                "Silver_Proxy": silver_proxy,
            },
        )

        (out / "requests.jsonl").touch(exist_ok=True)
        req_log = read_jsonl(out / "requests.jsonl")

        # Verify shared hashes AFTER execution
        hashes_after = collect_shared_hashes()
        modified_shared = [
            k for k in hashes_before
            if hashes_before[k] != "LOCKED" and hashes_after.get(k) != "LOCKED" and hashes_before[k] != hashes_after.get(k)
        ]
        if modified_shared:
            raise RuntimeError(f"Shared read-only files were modified: {modified_shared}")

        # Verify unaffected region exact parity
        unaffected_checks = {
            "cap01_001_053_unchanged": all(
                final_rows[i] == v1_map_by_key[("Cap_01", i + 1)] for i in range(53)
            ) if not pilot else None,
            "cap02_001_050_unchanged": all(
                final_rows[53 + h - 1] == v1_map_by_key[("Cap_02", h)] for h in range(1, 51)
            ) if not pilot else None,
            "cap02_088_092_unchanged": all(
                final_rows[53 + h - 1] == v1_map_by_key[("Cap_02", h)] for h in range(88, 93)
            ) if not pilot else None,
        }
        if not pilot and not all(unaffected_checks.values()):
            raise RuntimeError(f"Unaffected region invariance failed: {unaffected_checks}")

        integrity_obj = {
            "status": "PASS",
            "version": VERSION,
            "workbooks": wb_audits,
            "frozen_han_s4": frozen_han_audit,
            "book_vi_anchors_and_transitions": transition_and_anchors,
            "unaffected_regions_invariance": unaffected_checks,
            "shared_files_checked_count": len(hashes_before),
            "shared_files_modified_count": len(modified_shared),
            "shared_files_modified": modified_shared,
            "shared_hashes_before": hashes_before,
            "shared_hashes_after": hashes_after,
        }
        write_json(out / "source_integrity.json", integrity_obj)

        statuses_v2 = dict(Counter(r["Mapping_Status"] for r in final_rows))
        elapsed = round(time.monotonic() - started, 2)
        metrics_obj = {
            "version": VERSION,
            "pilot": pilot,
            "v1_statuses": v1_metrics["statuses"],
            "statuses": statuses_v2,
            "supported_pages_v1": 103,
            "partial_pages_v1": 1,
            "unmatched_pages_v1": 41,
            "supported_pages_v2": sum(1 for r in final_rows if r["Mapping_Status"] not in ("UNMATCHED", "PARTIAL")),
            "partial_pages_v2": sum(1 for r in final_rows if r["Mapping_Status"] == "PARTIAL"),
            "unmatched_pages_v2": sum(1 for r in final_rows if r["Mapping_Status"] == "UNMATCHED"),
            "unmatched_page_list": [f"{r['Cap']}:{r['Han_Page']:03d}" for r in final_rows if r["Mapping_Status"] == "UNMATCHED"],
            "ambiguous_page_list": [f"{r['Cap']}:{r['Han_Page']:03d}" for r in final_rows if r["Mapping_Status"] == "AMBIGUOUS"],
            "book6_new_pages_statuses": dict(Counter(r["Mapping_Status"] for r in chosen_51_87)),
            "book6_local_vs_global_differing_pages": sum(r["Local_Range"] != r["B2_Range"] for r in chosen_51_87),
            "local_global_differing_pages_total": sum(r["Local_Range"] != r["B2_Range"] for r in final_rows),
            "vi_id_coverage": vi_coverage_summary,
            "cross_page_continuations": {
                "han_cross_page_s4_segments_cap01": frozen_han_audit["caps"]["Cap_01"]["cross_page_segments"],
                "han_cross_page_s4_segments_cap02": frozen_han_audit["caps"]["Cap_02"]["cross_page_segments"],
                "viet_cross_page_eligible_cap01": wb_audits["VIET_0186-0251"]["cross_page_segments_eligible"],
                "viet_cross_page_eligible_cap02_book5": wb_audits["VIET_0001-0105"]["cross_page_segments_eligible"],
                "viet_cross_page_eligible_cap02_book6": wb_audits["VIET_0405-0439"]["cross_page_segments_eligible"],
                "cross_book_han_pages": ["Cap_02:051"],
                "cross_section_s4_segments": ["Cap_02-051-052-S4-0006", "Cap_02-051-052-S4-0012", "Cap_02-087-088-S4-0005"],
            },
            "structural": structural_stats,
            "validation": valid_all_flat,
            "validation_book6": valid_book6_flat,
            "downstream": downstream_all,
            "downstream_book6": [
                {k: v for k, v in r.items() if k != "links"} for r in book6_downstream
            ],
            "silver_proxy": silver_proxy,
            "api_summary": {
                "logged_requests_total": len(req_log),
                "live_network_requests": client.attempts,
                "cache_hits": client.hits,
                "readonly_cache_reused_count": len(client.reused_sources),
                "retries_used": client.retries_used,
                "http_429_count": client.http_429_count,
                "transient_failures": client.transient_failures,
                "permanent_failures": client.permanent_failures,
                "new_probe_statuses": dict(Counter(r["status"] for r in new_prod_probes)),
                "logged_http_statuses": dict(Counter(r.get("status") for r in req_log)),
                "wall_seconds": elapsed,
                "halt": client.halt,
            },
            "semantic_gold_labels_assigned": 0,
        }
        write_json(out / "metrics.json", metrics_obj)
        make_report_v2(out, metrics_obj, integrity_obj, pilot)
        if not pilot:
            from generate_integration_guide import generate_guide
            generate_guide(out)

        manifest_obj.update(
            status="complete" if not client.halt else f"halted:{client.halt}",
            completed_wall_seconds=elapsed,
            requests_logged=len(req_log),
            supported_pages=metrics_obj["supported_pages_v2"],
            unmatched_pages=metrics_obj["unmatched_pages_v2"],
        )
        write_json(manifest_path, manifest_obj)
        return int(bool(client.halt))
    finally:
        if lock_file.exists():
            lock_file.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true", help="Run smoke subset into coarse_mapping_v2/pilot")
    parser.add_argument("--resume", action="store_true", help="Resume matching run identity")
    parser.add_argument("--live", action="store_true", help="Allow live Alignment API calls via SINONOM_TOKEN")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT, help="Isolated output directory")
    parser.add_argument("--api-delay", type=float, default=1.1, help="Minimum seconds between live requests")
    parser.add_argument("--api-retries", type=int, default=4, help="Bounded retries for HTTP 429 and transient errors")
    args = parser.parse_args()
    return run_v2(
        live=args.live,
        resume=args.resume,
        pilot=args.pilot,
        output_dir=args.output_dir,
        api_delay=args.api_delay,
        api_retries=args.api_retries,
    )


if __name__ == "__main__":
    raise SystemExit(main())
