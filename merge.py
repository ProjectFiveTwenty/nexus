#!/usr/bin/env python3
"""Combine data/skeleton.txt and data/parts/* into data/nodes.json and data/edges.json.

Used while the graph is generated domain by domain. When two domains linked the
same pair of concepts from opposite sides, one link is kept, preferring the more
informative type.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tools"))
from nexus import DATA, EDGE_TYPES, PARTS, dump_rows, load_json, parse_skeleton  # noqa: E402

PRIORITY = {"part-of": 0, "explains": 1, "affects": 2, "applies-to": 3, "prerequisite": 4, "contrasts": 5}


def main():
    if "--overwrite" not in sys.argv:
        print("merge.py rebuilds data/nodes.json and data/edges.json from the generation files and\n"
              "discards any edits made since with manage.py. nodes.json and edges.json are now the\n"
              "source of truth. Run with --overwrite only if you really mean to regenerate.")
        sys.exit(1)
    sk = parse_skeleton()
    byid = {n["id"]: n for n in sk}
    chunks = sorted({n["chunk"] for n in sk})
    content, edges, problems = {}, [], []
    for c in chunks:
        for r in load_json(PARTS / f"{c}.nodes.json", []) or []:
            content[r["id"]] = r
        for e in load_json(PARTS / f"{c}.edges.json", []) or []:
            e = dict(e)
            e["_chunk"] = c
            edges.append(e)

    nodes = []
    for n in sk:
        r = content.get(n["id"])
        if not r or not (r.get("summary") or "").strip():
            problems.append(f"no summary for {n['id']}")
        nodes.append({
            "id": n["id"], "title": n["title"], "section": n["section"], "disc": n["disc"],
            "parent": n["parent"], "hub": n["hub"],
            "summary": (r or {}).get("summary", ""), "trap": (r or {}).get("trap"),
        })

    valid = []
    for e in edges:
        if e.get("s") not in byid or e.get("t") not in byid or e.get("type") not in EDGE_TYPES or e["s"] == e["t"]:
            problems.append(f"dropped invalid link {e.get('s')} -> {e.get('t')} ({e.get('type')})")
            continue
        valid.append(e)

    # One link per pair across domains; a domain's own deliberate double links survive.
    groups = defaultdict(list)
    for e in valid:
        groups[frozenset((e["s"], e["t"]))].append(e)
    kept, merged = [], 0
    for grp in groups.values():
        if len({e["_chunk"] for e in grp}) == 1:
            seen = set()
            for e in grp:
                k = (e["s"], e["t"], e["type"])
                if k not in seen:
                    seen.add(k)
                    kept.append(e)
            continue
        best = min(grp, key=lambda e: PRIORITY[e["type"]])
        same_chunk = [e for e in grp if e["_chunk"] == best["_chunk"]]
        kept.extend(same_chunk)
        merged += len(grp) - len(same_chunk)

    order = {n["id"]: i for i, n in enumerate(sk)}
    kept.sort(key=lambda e: (order[e["s"]], order[e["t"]]))
    out_edges = [{"s": e["s"], "t": e["t"], "type": e["type"], "why": e["why"].strip()} for e in kept]

    dump_rows(DATA / "nodes.json", nodes)
    dump_rows(DATA / "edges.json", out_edges)
    for p in problems:
        print("problem:", p)
    print(f"merged: {len(nodes)} concepts, {len(out_edges)} links ({merged} two-sided duplicates folded)")


if __name__ == "__main__":
    main()
