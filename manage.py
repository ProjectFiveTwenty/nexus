#!/usr/bin/env python3
"""Edit the MCAT Nexus graph from the command line. Every change makes a backup first
(data/backups/<timestamp>/).

  python3 manage.py add "Title" --disc "Physiology" --summary "..." [--parent <id>] [--hub]
                        [--trap "..."] [--id custom-id] [--section bb]
  python3 manage.py remove <id> [--dry-run] [--force]
  python3 manage.py link <from-id> <to-id> <type> "why sentence"
  python3 manage.py unlink <from-id> <to-id> [type]
  python3 manage.py ready <id> [<id> ...]   take concepts out of the pending queue once linked
  python3 manage.py status                  pending, thinly connected, and hierarchy gaps
  python3 manage.py context                 compact dump of the whole graph (for drawing links)

Concepts and hubs
  Every concept belongs to one of the categories already in the graph (--disc); its
  section (bb, cp, ps) follows from the category. A topic hub (--hub) is a top-level
  concept and has no parent. Any other concept may name a parent concept (--parent),
  and then it needs a part-of link to that parent:
      python3 manage.py link <id> <parent-id> part-of "why sentence"
  add does not create that link for you; `ready` refuses until it exists.

Pending
  New concepts start as "pending": they stay in nodes.json but are left out of the
  published page until their connections are drawn and `ready` is run.

Removing
  remove deletes the concept and every link touching it. A concept with subtopics is
  refused unless you pass --force, which moves its subtopics up to its own parent and
  points their part-of links there (or leaves them top level when it had no parent).
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SECTIONS = {"bb": "Bio & Biochem", "cp": "Chem & Phys", "ps": "Psych & Soc"}
EDGE_TYPES = ["part-of", "prerequisite", "explains", "affects", "applies-to", "contrasts"]
NODE_ORDER = ["id", "title", "section", "disc", "parent", "hub", "summary", "trap", "pending"]


def load():
    nodes = json.loads((DATA / "nodes.json").read_text(encoding="utf-8"))
    edges = json.loads((DATA / "edges.json").read_text(encoding="utf-8"))
    return nodes, edges


def backup():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = DATA / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("nodes.json", "edges.json"):
        shutil.copy(DATA / name, dest / name)
    return dest


def save(nodes, edges):
    """Write one object per line so git diffs stay readable."""
    def dump(rows):
        return "[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n"
    (DATA / "nodes.json").write_text(dump(nodes), encoding="utf-8")
    (DATA / "edges.json").write_text(dump(edges), encoding="utf-8")


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def die(msg):
    print("error:", msg)
    sys.exit(1)


def has_part_of(edges, child, parent):
    return any(e["s"] == child and e["t"] == parent and e["type"] == "part-of" for e in edges)


def link_cmd(child, parent):
    return f'python3 manage.py link {child} {parent} part-of "<why {child} belongs to {parent}>"'


def cmd_add(a):
    nodes, edges = load()
    byid = {n["id"]: n for n in nodes}
    nid = a.id or slug(a.title)
    if not nid:
        die("could not make an id from that title; pass --id")
    if nid in byid:
        die(f"id '{nid}' already exists")
    cats = {}
    for n in nodes:
        cats.setdefault(n["disc"], n["section"])
    if a.disc not in cats:
        die(f"unknown category '{a.disc}'. Use one of: {', '.join(sorted(cats))}")
    section = cats[a.disc]
    if a.section and a.section != section:
        die(f"category '{a.disc}' is in section {section}, not {a.section}")
    if a.hub and a.parent:
        die("a topic hub is top level and cannot have a parent")
    if a.parent and a.parent not in byid:
        die(f"parent '{a.parent}' does not exist")
    node = {
        "id": nid, "title": a.title, "section": section, "disc": a.disc,
        "parent": a.parent or None, "hub": bool(a.hub),
        "summary": a.summary, "trap": a.trap or None, "pending": True,
    }
    backup()
    nodes.append({k: node[k] for k in NODE_ORDER})
    save(nodes, edges)
    print(f"added '{nid}' as pending{' topic hub' if a.hub else ''} in {a.disc}.")
    print("Next: draw its connections, then run `python3 manage.py ready " + nid + "`.")
    if a.parent:
        print("It needs a part-of link to its parent first:")
        print("  " + link_cmd(nid, a.parent))


def cmd_remove(a):
    nodes, edges = load()
    byid = {n["id"]: n for n in nodes}
    if a.id not in byid:
        die(f"no concept with id '{a.id}'")
    gone = byid[a.id]
    children = [n for n in nodes if n.get("parent") == a.id]
    touching = [e for e in edges if a.id in (e["s"], e["t"])]
    print(f"'{a.id}' has {len(touching)} link(s):")
    for e in touching:
        print(f"  {e['s']} --{e['type']}--> {e['t']}")
    new_parent = gone.get("parent")
    if children:
        print(f"'{a.id}' has {len(children)} subtopic(s): {', '.join(c['id'] for c in children)}")
        if not a.force:
            die("refusing to remove a concept with subtopics. Pass --force to move them to "
                + (f"'{new_parent}'" if new_parent else "the top level") + ".")
    if a.dry_run:
        if children:
            print("with --force the subtopics would move to " + (new_parent or "the top level") + ".")
        print("dry run: nothing changed.")
        return
    dest = backup()
    rewritten = []
    if children:
        for c in children:
            c["parent"] = new_parent
        if new_parent:
            ptitle = byid[new_parent]["title"]
            for c in children:
                if not has_part_of(edges, c["id"], new_parent):
                    edges.append({"s": c["id"], "t": new_parent, "type": "part-of",
                                  "why": f"{c['title']} belongs under {ptitle}."})
                    rewritten.append(c["id"])
    nodes = [n for n in nodes if n["id"] != a.id]
    edges = [e for e in edges if a.id not in (e["s"], e["t"])]
    save(nodes, edges)
    print(f"removed '{a.id}' and {len(touching)} link(s). Backup: {dest.relative_to(ROOT)}")
    if children:
        where = f"'{new_parent}'" if new_parent else "the top level"
        print(f"moved {len(children)} subtopic(s) to {where}.")
        if rewritten:
            print("new part-of links carry a placeholder reason; rewrite them with unlink + link:")
            for cid in rewritten:
                print(f"  {cid} --part-of--> {new_parent}")


def cmd_link(a):
    nodes, edges = load()
    byid = {n["id"]: n for n in nodes}
    for x in (a.src, a.dst):
        if x not in byid:
            die(f"unknown concept '{x}'")
    if a.type not in EDGE_TYPES:
        die(f"type must be one of {EDGE_TYPES}")
    if a.src == a.dst:
        die("cannot link a concept to itself")
    if any(e["s"] == a.src and e["t"] == a.dst and e["type"] == a.type for e in edges):
        die("that exact link already exists")
    if not a.why.strip():
        die("a link needs a one-sentence reason")
    backup()
    edges.append({"s": a.src, "t": a.dst, "type": a.type, "why": a.why.strip()})
    save(nodes, edges)
    print(f"linked {a.src} --{a.type}--> {a.dst}")
    if a.type == "part-of" and byid[a.src].get("parent") != a.dst:
        print(f"note: '{a.src}' lists '{byid[a.src].get('parent')}' as its parent, so this part-of link "
              "does not change where it sits on the map.")


def cmd_unlink(a):
    nodes, edges = load()
    byid = {n["id"]: n for n in nodes}
    keep = [e for e in edges if not (e["s"] == a.src and e["t"] == a.dst and (not a.type or e["type"] == a.type))]
    removed = [e for e in edges if e not in keep]
    if not removed:
        die("no matching link")
    backup()
    save(nodes, keep)
    print(f"removed {len(removed)} link(s).")
    child = byid.get(a.src) or {}
    if any(e["type"] == "part-of" for e in removed) and child.get("parent") == a.dst and not child.get("hub"):
        print(f"warning: '{a.src}' still has parent '{a.dst}' and now lacks its part-of link; "
              "build.py will stop until you add one back:")
        print("  " + link_cmd(a.src, a.dst))


def cmd_ready(a):
    nodes, edges = load()
    byid = {n["id"]: n for n in nodes}
    deg = {}
    for e in edges:
        deg[e["s"]] = deg.get(e["s"], 0) + 1
        deg[e["t"]] = deg.get(e["t"], 0) + 1
    problems = []
    for nid in a.ids:
        n = byid.get(nid)
        if not n:
            problems.append(f"unknown concept '{nid}'")
        elif not deg.get(nid):
            problems.append(f"'{nid}' has no links yet; draw some first")
        elif n.get("parent") and not n.get("hub") and not has_part_of(edges, nid, n["parent"]):
            problems.append(f"'{nid}' has parent '{n['parent']}' but no part-of link to it. Run:\n  "
                            + link_cmd(nid, n["parent"]))
        elif n.get("parent") and n["parent"] not in byid:
            problems.append(f"'{nid}' names a parent '{n['parent']}' that does not exist")
    if problems:
        for p in problems:
            print("error:", p)
        print("nothing changed.")
        sys.exit(1)
    backup()
    for nid in a.ids:
        byid[nid].pop("pending", None)
        print(f"'{nid}' is now live ({deg[nid]} links).")
    save(nodes, edges)


def cmd_status(_):
    nodes, edges = load()
    byid = {n["id"]: n for n in nodes}
    deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        deg[e["s"]] = deg.get(e["s"], 0) + 1
        deg[e["t"]] = deg.get(e["t"], 0) + 1
    pending = [n for n in nodes if n.get("pending")]
    thin = [n for n in nodes if not n.get("pending") and deg[n["id"]] <= 2]
    hubs = sum(1 for n in nodes if n.get("hub"))
    print(f"{len(nodes)} concepts ({hubs} topic hubs), {len(edges)} links, {len(pending)} pending.\n")
    if pending:
        print("Pending (waiting for connections):")
        for n in pending:
            print(f"  {n['id']}: {n['title']}")
    if thin:
        print("\nThinly connected (2 links or fewer):")
        for n in thin:
            print(f"  {n['id']} ({deg[n['id']]})")
    gaps = [n for n in nodes if n.get("parent") and not n.get("hub") and n["parent"] in byid
            and not has_part_of(edges, n["id"], n["parent"])]
    bad = [n for n in nodes if n.get("parent") and (n["parent"] not in byid or n.get("hub"))]
    if gaps or bad:
        print("\nHierarchy problems (build.py stops on these):")
        for n in bad:
            why = "is a hub but has a parent" if n.get("hub") else f"names a missing parent '{n['parent']}'"
            print(f"  {n['id']} {why}")
        for n in gaps:
            print(f"  {n['id']} has no part-of link to its parent:\n    {link_cmd(n['id'], n['parent'])}")


def cmd_context(_):
    nodes, edges = load()
    print("CONCEPTS (id | section | category | parent | title | summary)")
    for n in nodes:
        flag = " [PENDING]" if n.get("pending") else ""
        hub = " [HUB]" if n.get("hub") else ""
        print(f"{n['id']} | {n['section']} | {n['disc']} | {n.get('parent') or '-'} | "
              f"{n['title']}{hub}{flag} | {n['summary']}")
    print("\nEXISTING LINKS (from --type--> to)")
    for e in edges:
        print(f"{e['s']} --{e['type']}--> {e['t']}")
    print("\nLINK TYPES:", ", ".join(EDGE_TYPES))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="add a pending concept")
    s.add_argument("title")
    s.add_argument("--disc", required=True, help="category, e.g. Physiology")
    s.add_argument("--summary", required=True)
    s.add_argument("--section", choices=sorted(SECTIONS), help="optional; must match the category")
    s.add_argument("--parent", help="id of the concept this one sits under")
    s.add_argument("--hub", action="store_true", help="make it a top-level topic hub")
    s.add_argument("--trap")
    s.add_argument("--id")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("remove", help="remove a concept and its links")
    s.add_argument("id")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="also move its subtopics up one level")
    s.set_defaults(fn=cmd_remove)

    s = sub.add_parser("link", help="add a link")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("type")
    s.add_argument("why")
    s.set_defaults(fn=cmd_link)

    s = sub.add_parser("unlink", help="remove a link")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("type", nargs="?")
    s.set_defaults(fn=cmd_unlink)

    s = sub.add_parser("ready", help="publish pending concepts")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_ready)

    sub.add_parser("status", help="pending, thin and hierarchy report").set_defaults(fn=cmd_status)
    sub.add_parser("context", help="dump the graph").set_defaults(fn=cmd_context)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
