#!/usr/bin/env python3
"""Statement and branch coverage measurement for CampusRide (standard library only).

This script exists so that coverage figures can be reproduced in an offline
environment where `coverage.py` / `pytest-cov` cannot be installed. It follows
the same definitions coverage.py uses:

* A **statement** is an executable line reported by ``code.co_lines()``.
* A **branch** is a line whose bytecode ends in a conditional jump and which can
  therefore transfer control to more than one destination line (``if``/``elif``,
  ``while``, ``for``, ternaries, boolean short-circuits, comprehension filters
  and ``assert``). Exception edges are excluded, exactly as coverage.py does by
  default.
* A branch is **fully taken** when every destination line was observed, and
  **partial** when only some were.

In CI, the authoritative figures come from coverage.py (see
``.github/workflows/ci.yml``); this script is the offline equivalent and is
expected to agree with it.

Usage:
    PYTHONPATH=src python scripts/measure_coverage.py --out docs/_coverage.json
"""

from __future__ import annotations

import argparse
import dis
import json
import os
import sys
from collections import defaultdict

# Conditional-jump opcodes: these are the points where control flow can take
# more than one path. Collected by name so the script survives bytecode churn
# between CPython versions.
_COND_JUMPS = {
    name
    for name in dis.opmap
    if "JUMP_IF" in name or name in {"FOR_ITER", "SEND", "JUMP_BACKWARD_NO_INTERRUPT"}
}
_COND_JUMPS.discard("JUMP_BACKWARD_NO_INTERRUPT")  # unconditional in practice


# --------------------------------------------------------------------------
# Static analysis: which lines are executable, and which lines are branches
# --------------------------------------------------------------------------
def _walk_code(code):
    """Yield a code object and every code object nested inside it."""
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield from _walk_code(const)


def _line_of(instruction):
    """Line number for an instruction, across CPython versions.

    ``Instruction.starts_line`` is an ``int`` up to 3.12 but a ``bool`` from
    3.13 on, where the number moved to ``line_number`` - so each candidate is
    checked for being an actual integer before it is trusted.
    """
    pos = getattr(instruction, "positions", None)
    if pos is not None and isinstance(pos.lineno, int):
        return pos.lineno
    for attribute in ("line_number", "starts_line"):
        value = getattr(instruction, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def analyse(path):
    """Return (statements, branches) for a source file.

    statements: set of executable line numbers
    branches:   {source_line: set(destination_lines)}
    """
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    code = compile(source, path, "exec")

    statements = set()
    branches = defaultdict(set)

    for sub in _walk_code(code):
        for _start, _end, line in sub.co_lines():
            if line:
                statements.add(line)

        instructions = list(dis.get_instructions(sub))
        if not instructions:
            continue

        # Resolve each instruction's line, carrying the last known line forward
        # for instructions that do not start a new line.
        lines = []
        current = None
        for ins in instructions:
            found = _line_of(ins)
            if found:
                current = found
            lines.append(current)

        offsets = {ins.offset: index for index, ins in enumerate(instructions)}

        for index, ins in enumerate(instructions):
            if ins.opname not in _COND_JUMPS:
                continue
            src_line = lines[index]
            if not src_line:
                continue
            # `except SomeError:` compiles to CHECK_EXC_MATCH + a conditional
            # jump. That edge is exception handling, not a decision in the
            # program's logic, and coverage.py leaves it out of branch
            # analysis - so it is skipped here too.
            if index and instructions[index - 1].opname == "CHECK_EXC_MATCH":
                continue

            def resolve(start_index):
                """First line at or after `start_index` that leaves `src_line`.

                Compiler bookkeeping (``STORE_FAST`` for a loop variable,
                ``END_FOR``, ``POP_TOP``) is attributed back to the statement
                that owns the branch, so both edges of a ``for`` loop would
                otherwise collapse onto the same line. Skipping forward to the
                first genuinely different line gives the statement-level
                destinations coverage.py reports.
                """
                for position in range(start_index, len(instructions)):
                    line = lines[position]
                    if line and line != src_line:
                        return line
                return None

            destinations = set()

            target_index = offsets.get(ins.argval)
            if target_index is not None:
                destinations.add(resolve(target_index))

            destinations.add(resolve(index + 1))

            destinations.discard(None)
            if len(destinations) >= 2:
                branches[src_line] |= destinations

    return statements, dict(branches)


# --------------------------------------------------------------------------
# Dynamic measurement: trace the test run
# --------------------------------------------------------------------------
class Tracer:
    """Records executed lines and line-to-line arcs for files under `root`."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.lines = defaultdict(set)
        self.arcs = defaultdict(set)
        self._last = {}

    def _watched(self, filename):
        if not filename or filename.startswith("<"):
            return False
        return os.path.realpath(filename).startswith(self.root)

    def __call__(self, frame, event, arg):
        filename = frame.f_code.co_filename
        if not self._watched(filename):
            return None
        if event == "call":
            return self
        if event == "line":
            line = frame.f_lineno
            key = id(frame)
            self.lines[filename].add(line)
            previous = self._last.get(key)
            if previous is not None:
                self.arcs[filename].add((previous, line))
            self._last[key] = line
        elif event == "return":
            self._last.pop(id(frame), None)
        return self

    def start(self):
        threading_hook()
        sys.settrace(self)

    def stop(self):
        sys.settrace(None)


def threading_hook():
    """Make the tracer apply to threads started during the run."""
    import threading

    threading.settrace(sys.gettrace())


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def build_report(source_root, tracer, omit=()):
    source_root = os.path.realpath(source_root)
    files = []
    for folder, _dirs, names in os.walk(source_root):
        for name in sorted(names):
            if name.endswith(".py") and name not in omit:
                files.append(os.path.join(folder, name))

    per_file = []
    for path in sorted(files):
        statements, branches = analyse(path)
        executed = {
            line for line in tracer.lines.get(path, set()) if line in statements
        }
        missing = sorted(statements - executed)

        observed_arcs = tracer.arcs.get(path, set())
        total_branches = 0
        taken_branches = 0
        partial = []
        for src_line, destinations in sorted(branches.items()):
            for destination in sorted(destinations):
                total_branches += 1
                if (src_line, destination) in observed_arcs:
                    taken_branches += 1
            hit = sum(
                1 for d in destinations if (src_line, d) in observed_arcs
            )
            if 0 < hit < len(destinations):
                partial.append(
                    {
                        "line": src_line,
                        "taken": hit,
                        "total": len(destinations),
                        "missed": sorted(
                            d
                            for d in destinations
                            if (src_line, d) not in observed_arcs
                        ),
                    }
                )

        per_file.append(
            {
                "file": os.path.relpath(path, os.path.dirname(source_root)),
                "statements": len(statements),
                "covered": len(executed),
                "missing": missing,
                "branches": total_branches,
                "branches_taken": taken_branches,
                "partial_branches": partial,
                "branch_points": len(branches),
            }
        )

    totals = {
        "statements": sum(f["statements"] for f in per_file),
        "covered": sum(f["covered"] for f in per_file),
        "branches": sum(f["branches"] for f in per_file),
        "branches_taken": sum(f["branches_taken"] for f in per_file),
        "branch_points": sum(f["branch_points"] for f in per_file),
    }
    totals["statement_pct"] = (
        100.0 * totals["covered"] / totals["statements"] if totals["statements"] else 100.0
    )
    totals["branch_pct"] = (
        100.0 * totals["branches_taken"] / totals["branches"] if totals["branches"] else 100.0
    )
    return {"files": per_file, "totals": totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="src/campusride")
    parser.add_argument("--tests", default="tests")
    parser.add_argument("--out", default="docs/_coverage.json")
    parser.add_argument(
        "--omit",
        default="__main__.py",
        help="comma-separated file names to exclude (entry-point shims by default, "
             "matching the omit list in .coveragerc)",
    )
    args = parser.parse_args()
    omit = {name.strip() for name in args.omit.split(",") if name.strip()}

    import pytest

    tracer = Tracer(args.source)
    tracer.start()
    try:
        exit_code = pytest.main([args.tests, "-q", "-p", "no:cacheprovider"])
    finally:
        tracer.stop()

    report = build_report(args.source, tracer, omit=omit)
    report["pytest_exit_code"] = int(exit_code)
    report["python"] = sys.version.split()[0]
    report["omitted"] = sorted(omit)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    totals = report["totals"]
    print()
    print(f"Statements : {totals['covered']}/{totals['statements']} "
          f"({totals['statement_pct']:.1f}%)")
    print(f"Branches   : {totals['branches_taken']}/{totals['branches']} "
          f"({totals['branch_pct']:.1f}%)")
    print(f"Written    : {args.out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
