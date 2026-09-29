#!/usr/bin/env python3
# box: — · lane: BD · read BRIDGES.md before editing
"""
ParkFind librarian: when something breaks, this points at the book.

The index is rebuilt from the code on every run, so it cannot go stale.
People write only two things by hand:
  - a three-line docstring on each method:  why: / boundary: / ugly:
  - one tag line at the top of each file:   # box: T2 · lane: DI · read BRIDGES.md before editing
    (the tag places the file on the drawings; the pointer sends any assistant to the rules first)

  python librarian.py status            card + call tree for anything named like "status"
  python librarian.py World.step -d 3   deeper tree
  python librarian.py --list            every method, grouped by file
  python librarian.py --check           missing headers + pipes that must be cut (exit 1 if any)

Standard library only. It reads source text; it never imports or runs the code it indexes,
so looking something up can never start the simulator or open a port.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import fnmatch
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP_DIRS = {".git", "out", "Fullpicture", "__pycache__", "venv", ".venv", "node_modules", ".idea", ".settings", "bin"}
HEADER_LABELS = ("why", "boundary", "ugly")

# The only hand-kept wiring: links a call graph cannot see because they cross a process or
# a language (the Java page calling the Python server over HTTP). (from, to, label), matched by
# the end of a node id. A link whose ends no longer exist is reported by --check, not ignored.
HAND_LINKS: list[tuple[str, str, str]] = []

# Pipes that must be cut, from Drawing 1 section 8 plus the trunk boundaries. Each rule is a
# pattern that must not appear in the files it covers. (id, what it means, covers, exempt, pattern)
CUTS = [
    ("X1", "World truth sits where the trunk or page could read it", ["*"], ["tests/*"], r"world_truth"),
    ("X2", "event note names a stall the sensor could not have seen", ["*"], ["tests/*"], r"hidden stall"),
    ("X3", "page invents occupancy", ["*.java", "WebPage"], [], r"new\s+Random\s*\(|Math\.random\s*\("),
    ("X4", "page makes its own clock instead of showing observation age", ["*.java", "WebPage"], [],
     r"LocalDateTime\.now\s*\(|System\.currentTimeMillis\s*\("),
    ("B1", "trunk imports the simulator (World would be one import away)", ["parkfind/*"], [],
     r"^\s*(from\s+sim\b|import\s+sim\b)"),
    ("B2", "truth file read outside the simulator and tests", ["*"], ["sim.py", "tests/*"], r"truth\.json"),
    ("B3", "trunk reads the wall clock instead of taking now as an argument", ["parkfind/*"],
     ["parkfind/clock.py"], r"datetime\.(now|utcnow)\s*\(|time\.time\s*\("),
]


# ---------------------------------------------------------------------------
# Finding and reading files
# ---------------------------------------------------------------------------

def source_files(root: Path) -> list[tuple[Path, str]]:
    """why: decide which files are books on the shelf, and in which language.
    boundary: reads the file tree under root, itself included; skips generated and private folders.
    ugly: Daniel's page is committed as 'WebPage' with no extension, so Java is also sniffed by content.
    """
    found = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix == ".py":
            found.append((p, "py"))
        elif p.suffix == ".java" or (p.suffix == "" and "public class" in _read(p)[:5000]):
            found.append((p, "java"))
    return found


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def file_tags(text: str) -> dict:
    """why: carry the Drawing 1 box and the Drawing 2 lane onto every method, and see the BRIDGES pointer.
    boundary: reads only the first ten lines; a tag lower down is ignored on purpose, since it would not be seen.
    ugly: an untagged file is shown as '?' rather than guessed from its name.
    """
    head = "\n".join(text.splitlines()[:10])
    box = re.search(r"box:\s*([^·\n]+)", head)
    lane = re.search(r"lane:\s*(\w+)", head)
    return {"box": box.group(1).strip() if box else "?", "lane": lane.group(1).strip() if lane else "?",
            "bridges": "read BRIDGES.md" in head}


def parse_header(doc: str | None) -> dict:
    """why: turn the why / boundary / ugly docstring into the three lines a card shows.
    boundary: reads the docstring text only; free prose outside the labels is ignored.
    ugly: a label split over several lines is joined; a missing label stays missing so --check sees it.
    """
    out: dict[str, str] = {}
    current = None
    for line in (doc or "").splitlines():
        m = re.match(r"\s*(why|boundary|ugly)\s*:\s*(.*)", line, re.I)
        if m:
            current = m.group(1).lower()
            out[current] = m.group(2).strip()
        elif current and line.strip():
            out[current] += " " + line.strip()
        else:
            current = None
    return out


# ---------------------------------------------------------------------------
# Python: exact, via ast
# ---------------------------------------------------------------------------

def index_python(path: Path, rel: str, text: str) -> tuple[list[dict], dict]:
    """why: read every function and method in one Python file into cards, with its raw calls.
    boundary: parses the text with ast; never imports the module, so nothing in it runs.
    ugly: a file that does not parse becomes one 'broken' card instead of stopping the whole index.
    """
    tags = file_tags(text)
    module = rel[:-3].replace("/", ".")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [_card(rel, module, "<does not parse>", e.lineno or 1, e.lineno or 1, "broken", tags)], {}
    imports = _python_imports(tree, module)
    cards = []
    module_calls = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cards.append(_python_card(node, rel, module, None, tags))
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    c = _python_card(item, rel, module, node.name, tags)
                    c["bases"] = bases
                    cards.append(c)
        else:
            module_calls += _python_calls(node)
    if module_calls:
        c = _card(rel, module, "<module>", 1, len(text.splitlines()), "module", tags)
        c["small"] = True
        c["raw_calls"] = module_calls
        cards.append(c)
    return cards, imports


def _card(rel, module, qual, line, end, kind, tags) -> dict:
    return {"id": f"{rel}::{qual}", "file": rel, "module": module, "qual": qual, "name": qual.split(".")[-1],
            "line": line, "end": end, "kind": kind, "box": tags["box"], "lane": tags["lane"],
            "args": [], "returns": "", "header": {}, "small": False, "raw_calls": [], "calls": [], "called_by": []}


def _python_card(fn, rel, module, cls, tags) -> dict:
    """why: one ast function node → one card: name, arguments, return type, header, raw calls.
    boundary: reads the node only; resolving calls into edges happens later in build_index.
    ugly: self and cls are dropped from 'in' so a method reads like the call site, not the definition.
    """
    qual = f"{cls}.{fn.name}" if cls else fn.name
    c = _card(rel, module, qual, fn.lineno, fn.end_lineno or fn.lineno, "method" if cls else "function", tags)
    c["cls"] = cls
    a = fn.args
    for arg in a.posonlyargs + a.args + a.kwonlyargs:
        if arg.arg in ("self", "cls"):
            continue
        c["args"].append(arg.arg + (f": {ast.unparse(arg.annotation)}" if arg.annotation else ""))
    c["returns"] = ast.unparse(fn.returns) if fn.returns else ""
    c["header"] = parse_header(ast.get_docstring(fn))
    # Dunders and three-line helpers are getters in spirit: the comment rule says no essays there.
    c["small"] = (fn.name.startswith("__") and fn.name.endswith("__")) or (c["end"] - c["line"]) <= 3
    c["raw_calls"] = _python_calls(fn)
    return c


def _python_calls(node) -> list[tuple[str, str]]:
    """why: list every call inside a function as (how it was written, name) for _resolve to pin down.
    boundary: records the call's spelling only; no guessing here.
    ugly: nested functions and lambdas count as their parent's calls, which is who a reader blames.
    """
    calls = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                calls.append(("name", f.id))
            elif isinstance(f, ast.Attribute):
                owner = f.value.id if isinstance(f.value, ast.Name) else ""
                calls.append((f"attr:{owner}", f.attr))
    return calls


def _python_imports(tree, module) -> dict:
    """why: know that 'OccupancyEvent' in sim.py means parkfind.event.OccupancyEvent once it moves.
    boundary: maps local names to dotted targets; stdlib names map too and simply never match a card.
    ugly: relative imports (from .event import X) are rebuilt from the file's own package.
    """
    pkg = module.rsplit(".", 1)[0] if "." in module else ""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names[a.asname or a.name.split(".")[0]] = ("module", a.name if a.asname else a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join(filter(None, [pkg, base]))
            for a in node.names:
                names[a.asname or a.name] = ("from", f"{base}.{a.name}" if base else a.name)
    return names


# ---------------------------------------------------------------------------
# Java: approximate, via masked text
# ---------------------------------------------------------------------------

JAVA_METHOD = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|synchronized|abstract)\s+)*"
    r"([\w<>\[\],.?]+)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws[\w\s,.]+)?\{", re.M)
JAVA_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "try", "do", "synchronized"}


def index_java(path: Path, rel: str, text: str) -> tuple[list[dict], dict]:
    """why: give Daniel's page the same cards as Python, so one search covers the whole program.
    boundary: pattern-matches method declarations and same-file calls; no Java parser, no compiling.
    ugly: text blocks full of CSS braces would fake methods, so string contents are blanked before matching.
    """
    tags = file_tags(text)
    masked = _mask_java_strings(text)
    cls = (re.search(r"\bclass\s+(\w+)", masked) or [None, rel])[1]
    decls = [m for m in JAVA_METHOD.finditer(masked) if m.group(2) not in JAVA_NOT_METHODS]
    names = {m.group(2) for m in decls}
    cards = []
    for m in decls:
        start = masked.index("{", m.end() - 1)
        stop = _match_brace(masked, start)
        line = masked.count("\n", 0, m.start()) + 1
        c = _card(rel, cls, f"{cls}.{m.group(2)}", line, masked.count("\n", 0, stop) + 1, "java", tags)
        c["cls"] = cls
        c["args"] = [a.strip() for a in " ".join(m.group(3).split()).split(",") if a.strip()]
        c["returns"] = m.group(1)
        c["header"] = parse_header(_java_comment_above(text, m.start()))
        c["small"] = (c["end"] - c["line"]) <= 3
        body = masked[start + 1:stop]
        c["raw_calls"] = [("name", n) for n in re.findall(r"\b(\w+)\s*\(", body) if n in names]
        cards.append(c)
    return cards, {}


def _mask_java_strings(text: str) -> str:
    """why: blank out strings and comments so braces and names inside them are not read as code.
    boundary: keeps every newline, so line numbers in the masked copy match the real file.
    ugly: Java text blocks (triple quotes) hold the page's CSS; they are blanked first.
    """
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r'"""[\s\S]*?"""', blank, text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', blank, text)
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", blank, text)
    text = re.sub(r"/\*[\s\S]*?\*/", blank, text)
    return re.sub(r"//[^\n]*", blank, text)


def _match_brace(text: str, open_at: int) -> int:
    """why: find where a Java method body ends, so its calls are not mixed with the next method's.
    boundary: expects masked text; raw text with braces in strings would miscount.
    ugly: an unclosed brace runs to end of file instead of raising, so a half-edited file still indexes.
    """
    depth = 0
    for i in range(open_at, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return i
    return len(text) - 1


def _java_comment_above(text: str, pos: int) -> str:
    """why: Java has no docstrings, so the why / boundary / ugly header lives in the comment above.
    boundary: accepts one /** */ block or a run of // lines directly above the method.
    ugly: a blank line between comment and method breaks the link, on purpose: loose comments are not headers.
    """
    before = text[:pos].rstrip()
    if before.endswith("*/"):
        return re.sub(r"^\s*(/\*\*?|\*/?)", "", before[before.rfind("/*"):], flags=re.M)
    lines = []
    for line in reversed(before.splitlines()):
        if not line.strip().startswith("//"):
            break
        lines.insert(0, line.strip()[2:])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wiring: raw call names → edges between cards
# ---------------------------------------------------------------------------

def build_index(root: Path) -> dict:
    """why: the whole shelf in one structure: cards, who-calls-whom both ways, and cut hits.
    boundary: pure read of the source tree; the same structure feeds the terminal and, later, the picture.
    ugly: a call it cannot pin down is linked to every candidate and marked dynamic, never silently dropped.
    """
    cards, imports_by_module, files = [], {}, {}
    for path, lang in source_files(root):
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        files[rel] = file_tags(text)
        got, imports = (index_python if lang == "py" else index_java)(path, rel, text)
        cards += got
        if got:
            imports_by_module[got[0]["module"]] = imports
    by_id = {c["id"]: c for c in cards}
    for c in cards:
        seen = set()
        for kind, name in c["raw_calls"]:
            for target, how in _resolve(c, kind, name, cards, imports_by_module.get(c["module"], {})):
                if target != c["id"] and (target, how) not in seen:
                    seen.add((target, how))
                    c["calls"].append({"to": target, "how": how})
    stale = []
    for src, dst, label in HAND_LINKS:
        a = [c for c in cards if c["id"].endswith(src)]
        b = [c for c in cards if c["id"].endswith(dst)]
        if len(a) == 1 and len(b) == 1:
            a[0]["calls"].append({"to": b[0]["id"], "how": f"hand: {label}"})
        else:
            stale.append((src, dst, label))
    for c in cards:
        for e in c["calls"]:
            by_id[e["to"]]["called_by"].append({"from": c["id"], "how": e["how"]})
    return {"cards": by_id, "files": files, "cuts": find_cuts(root), "stale_links": stale}


def _resolve(card, kind, name, cards, imports) -> list[tuple[str, str]]:
    """why: turn one written call into edges: direct, self, import, inferred or dynamic.
    boundary: matches against cards on the shelf only; stdlib and builtin calls resolve to nothing.
    ugly: obj.emit() could be any adapter; all candidates are returned and marked dynamic.
    """
    same_module = [c for c in cards if c["module"] == card["module"]]
    if kind == "name":
        hit = [c for c in same_module if c["qual"] in (name, f"{name}.__init__")]
        if not hit and name in imports:
            target = imports[name][1]
            mod, _, obj = target.rpartition(".")
            hit = [c for c in cards if c["module"] == mod and c["qual"] in (obj, f"{obj}.__init__")]
        if not hit and card["kind"] == "java":
            hit = [c for c in same_module if c["name"] == name]
        return [(c["id"], "direct") for c in hit]
    owner = kind.split(":", 1)[1]
    if owner in ("self", "cls") and card.get("cls"):
        classes = [card["cls"]] + [b.split(".")[-1] for b in card.get("bases", [])]
        for cls in classes:
            hit = [c for c in same_module if c["qual"] == f"{cls}.{name}"]
            if hit:
                return [(hit[0]["id"], "self")]
    if owner in imports and imports[owner][0] in ("module", "from"):
        mod = imports[owner][1]
        hit = [c for c in cards if c["module"] == mod and c["qual"] == name]
        if hit:
            return [(hit[0]["id"], "import")]
    if name.startswith("__"):
        return []
    hit = [c for c in cards if c["name"] == name and c["kind"] == "method"]
    if len(hit) == 1:
        return [(hit[0]["id"], "inferred")]
    return [(c["id"], "dynamic") for c in hit]


def find_cuts(root: Path) -> list[dict]:
    """why: turn the pipes-to-cut list into a check that names the file and line, not a memory.
    boundary: scans code files only (the same shelf as the index); docs and drawings are not code.
    ugly: a rule firing is a finding, not a crash; cuts scheduled for a later week still show until done.
    """
    hits = []
    for path, _lang in source_files(root):
        rel = path.relative_to(root).as_posix()
        if rel == "librarian.py":
            continue  # its own rule patterns would match themselves
        for cid, what, covers, exempt, pattern in CUTS:
            if not any(fnmatch.fnmatch(rel, g) for g in covers) or any(fnmatch.fnmatch(rel, g) for g in exempt):
                continue
            for n, line in enumerate(_read(path).splitlines(), 1):
                if re.search(pattern, line):
                    hits.append({"id": cid, "what": what, "file": rel, "line": n, "text": line.strip()[:90]})
    return hits


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

MARK = {"direct": "", "self": "", "import": "", "inferred": " ~inferred", "dynamic": " ?dynamic"}


def find(index: dict, query: str) -> list[dict]:
    """why: let a tired person type half a name and still land on the right card.
    boundary: matches on name, Class.name and file; returns candidates, never picks one at random.
    ugly: an exact name wins over substrings, so 'step' is World.step, not every method containing 'step'.
    """
    cards = list(index["cards"].values())
    q = query.lower()
    exact = [c for c in cards if q in (c["name"].lower(), c["qual"].lower(), c["id"].lower())]
    return exact or [c for c in cards if q in c["id"].lower()]


def print_card(index: dict, c: dict, depth: int) -> None:
    """why: one card plus both trees, the answer to 'what breaks if this breaks'.
    boundary: prints only; cycles are cut with a marker so a recursive pair cannot loop forever.
    ugly: a card without its three header lines says so in the card, where the reader will see it.
    """
    print(f"\n{c['qual']}   {c['file']}:{c['line']}   box {c['box']} · lane {c['lane']}")
    for label in HEADER_LABELS:
        text = c["header"].get(label)
        print(f"  {label:<9}{text if text else ('—' if c['small'] else '(missing: write it)')}")
    print(f"  in: {', '.join(c['args']) or '—'}      out: {c['returns'] or '—'}")
    print("  calls")
    _tree(index, c["id"], "calls", "to", depth, "  ", {c["id"]})
    print("  called by")
    _tree(index, c["id"], "called_by", "from", depth, "  ", {c["id"]})


def _tree(index, node_id, edge_key, end_key, depth, pad, seen) -> None:
    """why: draw callers or callees as an indented tree, depth levels down.
    boundary: prints only; seen carries the path so far, which is what makes a loop detectable.
    ugly: a node already on the path prints once with ↺ and stops, or A→B→A would never end.
    """
    edges = index["cards"][node_id][edge_key]
    if not edges and pad == "  ":
        print(f"{pad}└─ (nothing on the shelf)")
        return
    for i, e in enumerate(edges):
        last = i == len(edges) - 1
        t = index["cards"][e[end_key]]
        loop = e[end_key] in seen
        how = MARK.get(e["how"], f" [{e['how']}]")
        label = f"{pad}{'└─' if last else '├─'} {t['qual']}"
        print(f"{label:<44} {t['file']}:{t['line']}{how}{'  (↺ shown above)' if loop else ''}")
        if depth > 1 and not loop:
            _tree(index, e[end_key], edge_key, end_key, depth - 1, pad + ("   " if last else "│  "), seen | {e[end_key]})


def print_list(index: dict) -> None:
    """why: the whole shelf at a glance, with a mark for every card whose header is missing.
    boundary: prints only, grouped by file in line order.
    ugly: small helpers show '·' rather than '✗' so the list does not nag about getters.
    """
    by_file: dict[str, list[dict]] = {}
    for c in index["cards"].values():
        by_file.setdefault(c["file"], []).append(c)
    for f, cs in by_file.items():
        print(f"\n{f}   box {cs[0]['box']} · lane {cs[0]['lane']}")
        for c in sorted(cs, key=lambda c: c["line"]):
            ok = "✓" if all(c["header"].get(k) for k in HEADER_LABELS) else ("·" if c["small"] else "✗")
            print(f"  {ok} {c['qual']:<32} :{c['line']}")
    print("\n✓ header complete   · small, header optional   ✗ header missing")


def run_check(index: dict) -> int:
    """why: the done-rule as a command: every turn with new or pulled code ends with this passing.
    boundary: reports and sets the exit code; changes no file.
    ugly: cuts scheduled for later weeks keep it failing until done, which is the point, not a bug.
    """
    untagged = [(f, t) for f, t in index["files"].items() if t["box"] == "?" or t["lane"] == "?" or not t["bridges"]]
    for f, t in untagged:
        gaps = [k for k in ("box", "lane") if t[k] == "?"] + ([] if t["bridges"] else ["read BRIDGES.md pointer"])
        print(f"TAG     {f}  first ten lines missing {', '.join(gaps)}")
    missing = [c for c in index["cards"].values() if not c["small"] and not all(c["header"].get(k) for k in HEADER_LABELS)]
    for c in missing:
        gaps = [k for k in HEADER_LABELS if not c["header"].get(k)]
        print(f"HEADER  {c['file']}:{c['line']}  {c['qual']}  missing {', '.join(gaps)}")
    for h in index["cuts"]:
        print(f"CUT {h['id']:<3} {h['file']}:{h['line']}  {h['what']}\n          {h['text']}")
    for src, dst, label in index["stale_links"]:
        print(f"LINK    hand link '{label}' ({src} → {dst}) no longer matches exactly one method at each end")
    total = len(untagged) + len(missing) + len(index["cuts"]) + len(index["stale_links"])
    print(f"\n{len(index['cards'])} cards · {len(untagged)} untagged files · {len(missing)} missing headers · {len(index['cuts'])} cuts · "
          f"{len(index['stale_links'])} stale links → {'PASS' if total == 0 else 'FAIL'}")
    return 0 if total == 0 else 1


def main() -> None:
    """why: one entry point for search, list and check, so the team learns one command.
    boundary: parses arguments and prints; the index work lives in build_index.
    ugly: Windows consoles default to a code page without box characters, so output is forced to UTF-8.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="ParkFind librarian")
    p.add_argument("query", nargs="?", help="method or file to look up")
    p.add_argument("-d", "--depth", type=int, default=2, help="tree depth (default 2)")
    p.add_argument("--list", action="store_true", help="every method, grouped by file")
    p.add_argument("--check", action="store_true", help="missing headers and cuts; exit 1 if any")
    args = p.parse_args()

    index = build_index(HERE)
    if args.check:
        sys.exit(run_check(index))
    if args.list or not args.query:
        print_list(index)
        return
    hits = find(index, args.query)
    if not hits:
        names = sorted({c["name"] for c in index["cards"].values()})
        near = difflib.get_close_matches(args.query, names, n=5)
        print(f"Nothing on the shelf matches '{args.query}'." + (f" Close: {', '.join(near)}" if near else ""))
    elif len(hits) == 1:
        print_card(index, hits[0], args.depth)
    else:
        print(f"{len(hits)} matches — narrow it with Class.name or file::name:")
        for c in hits[:25]:
            print(f"  {c['id']}")


if __name__ == "__main__":
    main()
