#!/usr/bin/env python3
"""Syntax gate for the C# sources.

The build is the real gate, but it costs a full CI round trip to find a missing quote or a
bracket that moved. This walks every .cs file with tree-sitter and reports the exact line of
anything that is not valid C#, so a mistake is caught in a second instead of in ten minutes.

Run it before every commit:

    python3 ServerHelp/tools/csharp_gate.py

The grammar is optional: install it with `pip install tree_sitter tree_sitter_c_sharp`. When it
is missing the gate says so and passes, because CI still builds the code.
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_c_sharp
    except ImportError:
        print("tree_sitter is not installed here - skipping the syntax gate "
              "(pip install tree_sitter tree_sitter_c_sharp to enable it)")
        return 0

    parser = Parser(Language(tree_sitter_c_sharp.language()))
    pattern = os.path.join(ROOT, "src", "**", "*.cs")
    problems = []

    for path in sorted(glob.glob(pattern, recursive=True)):
        with open(path, "rb") as handle:
            source = handle.read()
        tree = parser.parse(source)
        found = []

        def walk(node):
            if node.type == "ERROR" or node.is_missing:
                snippet = source[node.start_byte:node.end_byte][:70].decode("utf-8", "replace")
                found.append((node.start_point[0] + 1, node.type, snippet.replace("\n", " ")))
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        if found:
            problems.append((os.path.relpath(path, ROOT), found[:4]))

    if not problems:
        print("syntax gate: clean")
        return 0

    print("syntax gate: {0} file(s) are not valid C#".format(len(problems)))
    for name, found in problems:
        for line, kind, snippet in found:
            print("  {0}:{1}: {2} near {3!r}".format(name, line, kind, snippet))
    return 1


if __name__ == "__main__":
    sys.exit(main())
