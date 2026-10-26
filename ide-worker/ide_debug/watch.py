"""Bounded data-path inspection through existing safe variable handles, never eval."""

import re

PATH = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:(?:\.[A-Za-z_$][A-Za-z0-9_$]*)|(?:\[(?:0|[1-9][0-9]{0,4})\])){0,7}$"
)


def valid_path(value):
    return type(value) is str and len(value) <= 128 and bool(PATH.fullmatch(value))


async def inspect_paths(adapter, args):
    expressions = args.get("expressions", [])
    if not 1 <= len(expressions) <= 16 or any(not valid_path(v) for v in expressions):
        raise ValueError("Invalid watch")
    if hasattr(adapter, "inspect_paths"):
        return await adapter.inspect_paths(args)
    cache = {}
    visits = 0

    async def children(ref):
        nonlocal visits
        if ref not in cache:
            if visits >= 1000:
                return []
            result = await adapter.command(
                "variables", {"variablesReference": ref, "start": 0, "count": 100}
            )
            cache[ref] = result.get("variables", [])[: min(100, 1000 - visits)]
            visits += len(cache[ref])
        return cache[ref]

    scopes = await adapter.command("scopes", {"frameId": args["frameId"]})
    roots = []
    for scope in scopes.get("scopes", [])[:4]:
        if not scope.get("expensive"):
            roots.extend(await children(scope["variablesReference"]))
    results = []
    for expression in expressions:
        parts = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|\[[0-9]+\]", expression)
        level, found = roots, None
        for i, part in enumerate(parts):
            names = (part, part[1:-1]) if part.startswith("[") else (part,)
            found = next((v for v in level if v.get("name") in names), None)
            if not found:
                break
            if i < len(parts) - 1:
                level = (
                    await children(found.get("variablesReference", 0))
                    if found.get("variablesReference")
                    else []
                )
        results.append(
            {
                "expression": expression,
                "available": bool(found),
                "value": (
                    str(found.get("value", ""))[:1024] if found else "<unavailable>"
                ),
            }
        )
    return {"watches": results}
