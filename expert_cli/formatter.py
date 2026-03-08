"""Output formatting for LSP responses."""

import json
import re

# LSP SymbolKind mapping
SYMBOL_KINDS = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "func", 13: "variable", 14: "constant", 15: "string",
    16: "number", 17: "boolean", 18: "array", 19: "object", 20: "key",
    21: "null", 22: "enum_member", 23: "struct", 24: "event", 25: "operator",
    26: "type_param",
}


def format_hover(result: dict | None, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2)

    if not result:
        return "No hover information available."

    contents = result.get("contents", "")

    # MarkupContent: {"kind": "markdown"|"plaintext", "value": "..."}
    if isinstance(contents, dict):
        text = contents.get("value", "")
    # String
    elif isinstance(contents, str):
        text = contents
    # MarkedString array
    elif isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, dict):
                parts.append(item.get("value", ""))
            else:
                parts.append(str(item))
        text = "\n\n".join(parts)
    else:
        text = str(contents)

    # Strip markdown code fences for cleaner terminal output
    text = re.sub(r"```\w*\n?", "", text)
    text = text.strip()

    # Truncate long output: show signature + first section only
    lines = text.split("\n")
    if len(lines) > 15:
        # Cut at first markdown heading (##) after the opening content,
        # or at 15 lines, whichever comes first
        cut_at = 15
        for i, line in enumerate(lines):
            if i > 2 and line.startswith("##"):
                cut_at = i
                break

        remaining = len(lines) - cut_at
        text = "\n".join(lines[:cut_at]).rstrip()
        text += f"\n\n... ({remaining} more lines, use --json for full output)"

    return text


def format_definition(result, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2)

    if not result:
        return "No definition found."

    # Can be a single Location or a list
    locations = result if isinstance(result, list) else [result]

    lines = []
    for loc in locations:
        uri = loc.get("uri", loc.get("targetUri", ""))
        path = uri.replace("file://", "")

        range_ = loc.get("range", loc.get("targetRange", {}))
        start = range_.get("start", {})
        line = start.get("line", 0) + 1  # LSP is 0-based
        col = start.get("character", 0) + 1

        lines.append(f"{path}:{line}:{col}")

    return "\n".join(lines)


def format_references(result, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2)

    if not result:
        return "No references found."

    lines = []
    for loc in result:
        uri = loc.get("uri", "")
        path = uri.replace("file://", "")
        start = loc.get("range", {}).get("start", {})
        line = start.get("line", 0) + 1
        col = start.get("character", 0) + 1
        lines.append(f"{path}:{line}:{col}")

    return "\n".join(lines)


def format_symbols(result, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2)

    if not result:
        return "No symbols found."

    lines = []
    for sym in result:
        kind_num = sym.get("kind", 0)
        kind = SYMBOL_KINDS.get(kind_num, f"kind:{kind_num}")
        name = sym.get("name", "?")

        # DocumentSymbol has range, SymbolInformation has location
        if "range" in sym:
            start = sym["range"]["start"]
        elif "location" in sym:
            start = sym["location"]["range"]["start"]
        else:
            start = {"line": 0, "character": 0}

        line = start.get("line", 0) + 1
        col = start.get("character", 0) + 1

        lines.append(f"{kind:<8s} {name:<36s} {line}:{col}")

        # Recurse into children (DocumentSymbol)
        children = sym.get("children", [])
        for child in children:
            ck = SYMBOL_KINDS.get(child.get("kind", 0), "?")
            cn = child.get("name", "?")
            cs = child.get("range", {}).get("start", {})
            cl = cs.get("line", 0) + 1
            cc = cs.get("character", 0) + 1
            lines.append(f"  {ck:<6s} {cn:<34s} {cl}:{cc}")

    return "\n".join(lines)


def format_workspace_symbols(result, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2)

    if not result:
        return "No symbols found."

    lines = []
    for sym in result:
        kind_num = sym.get("kind", 0)
        kind = SYMBOL_KINDS.get(kind_num, f"kind:{kind_num}")
        name = sym.get("name", "?")
        loc = sym.get("location", {})
        uri = loc.get("uri", "")
        path = uri.replace("file://", "")
        start = loc.get("range", {}).get("start", {})
        line = start.get("line", 0) + 1
        col = start.get("character", 0) + 1

        lines.append(f"{kind:<8s} {name:<36s} {path}:{line}:{col}")

    return "\n".join(lines)
