#!/usr/bin/env python3
"""Validate the MCAT Nexus graph data and build one self-contained viewer page.

Usage:  python3 build.py              validate, refresh the layout if needed, write mcat-web.html
        python3 build.py --check      validate only
        python3 build.py --relayout   rerun the layout even if the graph has not changed
        python3 build.py --curated=PATH   read the curated interleave table from PATH
                                          (or set NEXUS_CURATED=PATH; default data/interleave_curated.json)
        python3 build.py --out=PATH   write the page somewhere other than mcat-web.html

Interleaving data: data/hub_members.json and data/interleave_candidates.json (written by
tools/interleave.py) plus the optional curated table are inlined next to the graph. The page
shows each hub's five partners; hubs missing from the curated table use the candidates.

Positions come from data/positions.json, written by `node tools/layout.mjs`. The file
stores a hash of the live concepts and links. When the hash no longer matches and
node (plus node_modules) is available, the layout is rerun. Otherwise the old
positions are kept for concepts they cover and the page places new concepts near
their parent.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
SECTIONS = {"bb", "cp", "ps"}
EDGE_TYPES = {"part-of", "prerequisite", "explains", "affects", "applies-to", "contrasts"}
NODE_KEYS = {"id", "title", "section", "disc", "summary"}
POSITIONS = ROOT / "data" / "positions.json"
LAYOUT_SCRIPT = ROOT / "tools" / "layout.mjs"


def load(name):
    with open(ROOT / "data" / name, encoding="utf-8") as f:
        return json.load(f)


def validate(nodes, edges):
    errors, warnings = [], []
    ids = [n.get("id") for n in nodes]
    dupes = [i for i, c in Counter(ids).items() if c > 1]
    for d in dupes:
        errors.append(f"duplicate node id: {d}")
    idset = set(ids)
    byid = {n.get("id"): n for n in nodes}

    for n in nodes:
        missing = NODE_KEYS - set(n)
        if missing:
            errors.append(f"node {n.get('id')}: missing {sorted(missing)}")
        if n.get("section") not in SECTIONS:
            errors.append(f"node {n.get('id')}: bad section {n.get('section')!r}")
        if len(n.get("summary") or "") < 40:
            warnings.append(f"node {n.get('id')}: summary is very short")

    seen = set()
    deg = defaultdict(int)
    adj = defaultdict(set)
    part_of = set()
    for e in edges:
        label = f"edge {e.get('s')} -> {e.get('t')}"
        for k in ("s", "t"):
            if e.get(k) not in idset:
                errors.append(f"{label}: unknown node {e.get(k)!r}")
        if e.get("type") not in EDGE_TYPES:
            errors.append(f"{label}: bad type {e.get('type')!r}")
        if not (e.get("why") or "").strip():
            errors.append(f"{label}: empty 'why' sentence")
        if e.get("s") == e.get("t"):
            errors.append(f"{label}: self loop")
        key = (e.get("s"), e.get("t"), e.get("type"))
        if key in seen:
            errors.append(f"{label}: duplicate ({e.get('type')})")
        seen.add(key)
        if e.get("type") == "part-of":
            part_of.add((e.get("s"), e.get("t")))
        deg[e.get("s")] += 1
        deg[e.get("t")] += 1
        adj[e.get("s")].add(e.get("t"))
        adj[e.get("t")].add(e.get("s"))

    # Hierarchy: parents exist, hubs are roots, children link to their parent, no cycles.
    for n in nodes:
        nid, parent = n.get("id"), n.get("parent")
        if n.get("hub") and parent:
            errors.append(f"hub {nid} has a parent ({parent}); hubs must be top level")
        if not parent:
            continue
        if parent not in idset:
            errors.append(f"node {nid}: parent {parent!r} does not exist")
            continue
        if parent == nid:
            errors.append(f"node {nid}: is its own parent")
            continue
        if not n.get("hub") and (nid, parent) not in part_of:
            errors.append(f"node {nid}: no part-of link to its parent {parent} "
                          f"(python3 manage.py link {nid} {parent} part-of \"...\")")
    for n in nodes:
        cur, chain = n.get("id"), set()
        while cur and cur in byid and cur not in chain:
            chain.add(cur)
            cur = byid[cur].get("parent")
        if cur and cur in chain:
            errors.append(f"node {n.get('id')}: parent chain loops back to {cur}")

    pending = {n["id"] for n in nodes if n.get("pending")}
    for i in idset:
        if deg[i] == 0 and i not in pending:
            errors.append(f"orphan node (no edges): {i}")
        if deg[i] > 0 and i in pending:
            warnings.append(f"{i} has links but is still marked pending")
    if pending:
        warnings.append(f"{len(pending)} pending concept(s) waiting for connections: {sorted(pending)}")

    # connected components
    left, comps = set(idset), 0
    while left:
        comps += 1
        stack = [left.pop()]
        while stack:
            cur = stack.pop()
            for nb in adj[cur]:
                if nb in left:
                    left.remove(nb)
                    stack.append(nb)
    if comps > 1:
        warnings.append(f"graph has {comps} disconnected pieces")

    sec = {n["id"]: n.get("section") for n in nodes}
    cross = sum(1 for e in edges if sec.get(e["s"]) != sec.get(e["t"]))
    stats = {
        "nodes": len(nodes),
        "hubs": sum(1 for n in nodes if n.get("hub")),
        "edges": len(edges),
        "cross_section_edges": cross,
        "edge_types": dict(Counter(e["type"] for e in edges)),
        "most_connected": sorted(deg.items(), key=lambda kv: -kv[1])[:5],
    }
    return errors, warnings, stats


def live_graph(nodes, edges):
    """Pending concepts and their links stay off the page. A live concept whose parent is
    pending hangs from the nearest live ancestor instead. Mirrors liveGraph() in tools/layout.mjs."""
    byid = {n["id"]: n for n in nodes}
    live = {n["id"] for n in nodes if not n.get("pending")}

    def eff_parent(n):
        p, seen = n.get("parent"), set()
        while p and p not in live and p in byid and p not in seen:
            seen.add(p)
            p = byid[p].get("parent")
        return p if p in live else None

    out = [{**n, "parent": eff_parent(n)} for n in nodes if n["id"] in live]
    return out, [e for e in edges if e["s"] in live and e["t"] in live]


def graph_hash(nodes, edges, version):
    """Same recipe as graphHash() in tools/layout.mjs."""
    lines = [f"N\t{n['id']}\t{n['disc']}\t{n.get('parent') or ''}\t{1 if n.get('hub') else 0}" for n in nodes]
    lines += [f"E\t{e['s']}\t{e['t']}\t{e['type']}" for e in edges]
    lines.sort()
    return hashlib.sha256("\n".join([version] + lines).encode("utf-8")).hexdigest()


def layout_version():
    try:
        for line in LAYOUT_SCRIPT.read_text(encoding="utf-8").splitlines():
            if "LAYOUT_VERSION =" in line:
                return line.split("=", 1)[1].strip().strip(";").strip('"')
    except OSError:
        pass
    return None


def read_positions():
    try:
        doc = json.loads(POSITIONS.read_text(encoding="utf-8"))
        return doc.get("hash"), doc.get("positions") or {}
    except (OSError, ValueError):
        return None, {}


def refresh_layout(nodes, edges, force=False):
    """Return positions for the live graph, rerunning the layout when the graph changed."""
    version = layout_version()
    want = graph_hash(nodes, edges, version) if version else None
    have, positions = read_positions()
    if want and have == want and not force:
        print("layout: up to date")
        return positions
    node = shutil.which("node")
    deps = all((ROOT / "node_modules" / p).exists() for p in ("cytoscape", "cytoscape-fcose"))
    if node and deps and version:
        print("layout: graph changed, rerunning tools/layout.mjs" if have else "layout: computing positions")
        try:
            r = subprocess.run([node, str(LAYOUT_SCRIPT)], cwd=ROOT, capture_output=True, text=True, timeout=300)
            if r.returncode == 0:
                print(r.stdout.strip())
                new_hash, positions = read_positions()
                if new_hash != want:
                    print("warning: layout hash differs from build.py's hash; check both recipes match")
                return positions
            print("warning: layout failed:", (r.stderr or r.stdout).strip()[-800:])
        except (OSError, subprocess.SubprocessError) as exc:
            print("warning: layout could not run:", exc)
    else:
        why = "node is not installed" if not node else "run `npm install` first" if not deps else "tools/layout.mjs missing"
        print(f"warning: layout is stale and cannot rerun ({why}); keeping old positions")
    return positions


def arg_value(name):
    for a in sys.argv[1:]:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def load_optional(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        print(f"warning: could not read {path}: {exc}")
        return None


def interleave_payload(nodes, edges):
    """Hub membership plus five interleave partners per hub, trimmed for the page.

    Shape: {"hubOf": {concept: hub}, "cur": {hub: [[partner, why, [[a, b], ...]], ...]},
            "cand": {hub: [[partner, [[a, b], ...]], ...]}}
    "cur" comes from the curated table (optional). "cand" holds the top candidates from
    tools/interleave.py; the page uses them for hubs the curated table does not cover yet.
    Prompt/answer fields in the curated table are ignored.
    """
    live = {n["id"]: n for n in nodes}
    hubs = {i for i, n in live.items() if n.get("hub")}

    members = load_optional(ROOT / "data" / "hub_members.json") or {}
    hub_of = {c: h for c, h in members.items() if c in live and h in hubs and c != h}
    if not members:
        print("note: data/hub_members.json missing; the page maps concepts to their top ancestor")

    def pairs_of(raw):
        out = []
        for p in raw or []:
            if isinstance(p, dict):
                p = [p.get("s"), p.get("t")]
            if isinstance(p, list) and len(p) == 2 and p[0] in live and p[1] in live:
                out.append([p[0], p[1]])
        return out

    cand = {}
    raw = load_optional(ROOT / "data" / "interleave_candidates.json") or {}
    if not raw:
        print("note: data/interleave_candidates.json missing; run python3 tools/interleave.py")
    for h, lst in raw.items():
        if h not in hubs or not isinstance(lst, list):
            continue
        rows = [c for c in lst if isinstance(c, dict) and c.get("hub") in hubs and c.get("hub") != h]
        rows.sort(key=lambda c: -float(c.get("score", 0) or 0))
        cand[h] = [[c["hub"], pairs_of(c.get("bridges"))[:4]] for c in rows[:8]]

    cur_path = arg_value("--curated") or os.environ.get("NEXUS_CURATED") or str(ROOT / "data" / "interleave_curated.json")
    raw_cur = load_optional(cur_path)
    curated = {}
    if isinstance(raw_cur, dict):
        dropped = 0
        for h, lst in raw_cur.items():
            if h not in hubs or not isinstance(lst, list):
                dropped += 1
                continue
            rows, seen = [], set()
            for c in lst:
                if not isinstance(c, dict) or c.get("hub") not in hubs or c.get("hub") == h or c.get("hub") in seen:
                    dropped += 1
                    continue
                seen.add(c["hub"])
                rows.append([c["hub"], str(c.get("why") or ""), pairs_of(c.get("bridges"))[:4]])
            if rows:
                curated[h] = rows[:5]
        print(f"interleave: curated table from {cur_path}: {len(curated)} of {len(hubs)} hubs" +
              (f", {dropped} entries dropped" if dropped else ""))
    else:
        print("interleave: no curated table; every hub uses link-analysis suggestions")
    fallback = sorted(h for h in hubs if h not in curated)
    if fallback:
        print(f"interleave: {len(fallback)} hub(s) fall back to link analysis: {fallback[:12]}" + (" ..." if len(fallback) > 12 else ""))
    return {"hubOf": hub_of, "cur": curated, "cand": cand}


def main():
    nodes, edges = load("nodes.json"), load("edges.json")
    errors, warnings, stats = validate(nodes, edges)
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("ERROR:", e)
    print(json.dumps(stats, indent=2))
    if errors:
        print(f"\n{len(errors)} error(s). Build stopped.")
        sys.exit(1)
    if "--check" in sys.argv:
        print("\nData is valid.")
        return
    nodes, edges = live_graph(nodes, edges)
    positions = refresh_layout(nodes, edges, force="--relayout" in sys.argv)
    live = {n["id"] for n in nodes}
    pos = {k: v for k, v in positions.items() if k in live}
    missing = len(live) - len(pos)
    if not pos:
        print("note: no stored positions; the page will run a live layout when it opens")
    elif missing:
        print(f"note: {missing} concept(s) have no stored position; the page places them near their parent")

    template = (ROOT / "viewer.template.html").read_text(encoding="utf-8")
    data = {"nodes": nodes, "edges": edges, "pos": pos}
    data["il"] = interleave_payload(nodes, edges)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    out = template.replace("/*__GRAPH_DATA__*/null", payload)
    dest = Path(arg_value("--out") or ROOT / "mcat-web.html")
    dest.write_text(out, encoding="utf-8")
    print(f"\nWrote {dest.name} ({len(out) // 1024} KB)")


if __name__ == "__main__":
    main()
