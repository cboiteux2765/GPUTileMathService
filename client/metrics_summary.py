#!/usr/bin/env python3
import argparse
import math
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.request import urlopen


SAMPLE_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{.*\})?\s+([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)$')

def fetch_metrics(host: str) -> str:
    url = host.rstrip("/") + "/metrics"
    with urlopen(url, timeout=5) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_labels(label_blob: str) -> Dict[str, str]:
    # label_blob like {a="b",le="0.5"}
    if not label_blob:
        return {}
    s = label_blob.strip()
    if s[0] == "{":
        s = s[1:-1]
    labels = {}
    if not s.strip():
        return labels
    # split on commas that are not inside quotes (simple enough for our labels)
    parts = []
    cur, in_q = [], False
    for ch in s:
        if ch == '"':
            in_q = not in_q
        if ch == "," and not in_q:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))

    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        labels[k] = v
    return labels


def parse_exposition(text: str) -> Dict[str, List[Tuple[Dict[str, str], float]]]:
    series = defaultdict(list)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = SAMPLE_RE.match(line)
        if not m:
            continue
        name, label_blob, val = m.group(1), m.group(2), m.group(3)
        labels = parse_labels(label_blob or "")
        series[name].append((labels, float(val)))
    return series


@dataclass(frozen=True)
class HistKey:
    base: str
    labels: Tuple[Tuple[str, str], ...]  # sorted labels excluding 'le'


@dataclass
class HistAgg:
    buckets: Dict[float, float]  # le -> cumulative count
    inf_count: float
    sum: float
    count: float


def group_histograms(series: Dict[str, List[Tuple[Dict[str, str], float]]], base: str) -> Dict[HistKey, HistAgg]:
    # Prometheus histograms have: base_bucket{le="..."} , base_sum , base_count
    buckets_name = base + "_bucket"
    sum_name = base + "_sum"
    count_name = base + "_count"

    sums = {}
    counts = {}

    for labels, v in series.get(sum_name, []):
        k = HistKey(base, tuple(sorted((kk, vv) for kk, vv in labels.items())))
        sums[k] = v

    for labels, v in series.get(count_name, []):
        k = HistKey(base, tuple(sorted((kk, vv) for kk, vv in labels.items())))
        counts[k] = v

    buckets = defaultdict(dict)
    inf_counts = defaultdict(float)

    for labels, v in series.get(buckets_name, []):
        le_str = labels.get("le")
        if le_str is None:
            continue
        labels_wo = {k: vv for k, vv in labels.items() if k != "le"}
        k = HistKey(base, tuple(sorted(labels_wo.items())))
        if le_str == "+Inf":
            inf_counts[k] = v
            continue
        try:
            le = float(le_str)
        except ValueError:
            continue
        buckets[k][le] = v

    out = {}
    keys = set(sums.keys()) | set(counts.keys()) | set(buckets.keys()) | set(inf_counts.keys())
    for k in keys:
        out[k] = HistAgg(
            buckets=dict(sorted(buckets.get(k, {}).items(), key=lambda x: x[0])),
            inf_count=inf_counts.get(k, 0.0),
            sum=sums.get(k, 0.0),
            count=counts.get(k, 0.0),
        )
    return out


def quantile_from_buckets(buckets: Dict[float, float], total: float, q: float) -> float:
    if total <= 0:
        return float("nan")
    target = q * total
    for le, c in buckets.items():
        if c >= target:
            return le
    return float("inf")


def fmt_ms(x: float) -> str:
    if math.isnan(x):
        return "n/a"
    if math.isinf(x):
        return "inf"
    if x >= 1000:
        return f"{x/1000:.2f}s"
    return f"{x:.2f}ms"


def label_get(labels: Tuple[Tuple[str, str], ...], k: str, default: str = "-") -> str:
    d = dict(labels)
    return d.get(k, default)


def print_table(title: str, rows: List[List[str]]) -> None:
    print(title)
    if not rows:
        print("  (none)")
        return
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  " + "  ".join(r[i].ljust(widths[i]) for i in range(len(r))))
    print()


def render_dashboard(host: str) -> None:
    text = fetch_metrics(host)
    series = parse_exposition(text)

    # Simple gauges
    jobs_in_mem = series.get("jobs_in_memory", [({}, 0.0)])[0][1] if series.get("jobs_in_memory") else 0.0

    # Counters: submitted/completed
    submitted = defaultdict(float)
    for labels, v in series.get("jobs_submitted_total", []):
        key = (labels.get("op", "-"), labels.get("dtype", "-"), labels.get("simulate", "-"))
        submitted[key] += v

    completed = defaultdict(float)
    for labels, v in series.get("jobs_completed_total", []):
        key = (labels.get("op", "-"), labels.get("dtype", "-"), labels.get("state", "-"))
        completed[key] += v

    # Histograms
    e2e = group_histograms(series, "job_end_to_end_ms")
    comp = group_histograms(series, "job_compute_ms")

    # Header
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 72)
    print(f" GPU Tile Math Service — Metrics Summary  ({ts})")
    print("=" * 72)
    print(f" Host: {host}")
    print(f" Jobs tracked (in-memory gauge): {int(jobs_in_mem)}")
    print()

    # Submitted table
    sub_rows = [["op", "dtype", "simulate", "submitted_total"]]
    total_sub = 0.0
    for (op, dt, sim), v in sorted(submitted.items()):
        sub_rows.append([op, dt, sim, f"{int(v)}"])
        total_sub += v
    sub_rows.append(["-", "-", "-", f"{int(total_sub)}"])
    print_table("Jobs submitted:", sub_rows)

    # Completed table
    comp_rows = [["op", "dtype", "state", "completed_total"]]
    total_done = 0.0
    total_fail = 0.0
    for (op, dt, st), v in sorted(completed.items()):
        comp_rows.append([op, dt, st, f"{int(v)}"])
        if st == "done":
            total_done += v
        if st == "failed":
            total_fail += v
    comp_rows.append(["-", "-", "done", f"{int(total_done)}"])
    comp_rows.append(["-", "-", "failed", f"{int(total_fail)}"])
    print_table("Jobs completed:", comp_rows)

    # Histogram summary helper
    def hist_rows(title_base: str, h: Dict[HistKey, HistAgg]) -> List[List[str]]:
        rows = [["op", "dtype", "simulate", "count", "avg", "p50", "p95", "p99"]]
        for k, agg in sorted(h.items(), key=lambda kv: kv[0].labels):
            op = label_get(k.labels, "op")
            dt = label_get(k.labels, "dtype")
            sim = label_get(k.labels, "simulate")
            count = agg.count
            avg = (agg.sum / count) if count > 0 else float("nan")
            p50 = quantile_from_buckets(agg.buckets, count, 0.50)
            p95 = quantile_from_buckets(agg.buckets, count, 0.95)
            p99 = quantile_from_buckets(agg.buckets, count, 0.99)
            rows.append([op, dt, sim, f"{int(count)}", fmt_ms(avg), fmt_ms(p50), fmt_ms(p95), fmt_ms(p99)])
        return rows

    print_table("Latency (end-to-end):", hist_rows("job_end_to_end_ms", e2e))
    print_table("Compute time (CPU mode in Feature 1):", hist_rows("job_compute_ms", comp))

    print("Tip: run with --watch 1 to refresh every second.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--watch", type=float, default=0.0, help="Refresh interval seconds (0 = run once)")
    args = ap.parse_args()

    if args.watch and args.watch > 0:
        try:
            while True:
                # Clear screen
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
                render_dashboard(args.host)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return
    else:
        render_dashboard(args.host)


if __name__ == "__main__":
    main()