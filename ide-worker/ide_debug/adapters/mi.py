"""Bounded GDB/MI parser: recursive records, lists and C strings."""

import json
import re


def parse(line):
    match = re.match(r"^(\d*)([\^*+=~@&])(.*)$", line)
    if not match:
        return None
    token, kind, rest = match.groups()
    if kind in "~@&":
        try:
            return {"kind": kind, "text": json.loads(rest)}
        except ValueError:
            return {"kind": kind, "text": rest}
    name, _, payload = rest.partition(",")
    pos = 0

    def value(depth=0):
        nonlocal pos
        if depth > 32 or pos >= len(payload):
            raise ValueError("Invalid MI value")
        if payload[pos] == '"':
            # MI escapes are C strings. GDB uses JSON-compatible common escapes;
            # octal sequences appear in program values and remain escaped text.
            start = pos
            pos += 1
            while pos < len(payload):
                char = payload[pos]
                pos += 1
                if char == "\\":
                    pos += 1
                elif char == '"':
                    raw = payload[start:pos]
                    try:
                        return json.loads(raw)
                    except ValueError:
                        return raw[1:-1]
            raise ValueError("Truncated MI string")
        if payload[pos] in "[{":
            end = "]" if payload[pos] == "[" else "}"
            array = end == "]"
            pos += 1
            result = [] if array else {}
            while pos < len(payload) and payload[pos] != end:
                key = re.match(r"([A-Za-z0-9_-]+)=", payload[pos:])
                if key:
                    pos += len(key[0])
                    item = {key[1]: value(depth + 1)}
                    if array:
                        result.append(item)
                    else:
                        result.update(item)
                else:
                    item = value(depth + 1)
                    if not array:
                        raise ValueError("Invalid MI tuple")
                    result.append(item)
                if pos < len(payload) and payload[pos] == ",":
                    pos += 1
            if pos >= len(payload):
                raise ValueError("Truncated MI collection")
            pos += 1
            return result
        start = pos
        while pos < len(payload) and payload[pos] not in ",]}":
            pos += 1
        return payload[start:pos]

    result = {}
    while pos < len(payload):
        key = re.match(r"([A-Za-z0-9_-]+)=", payload[pos:])
        if not key:
            raise ValueError("Invalid MI record")
        pos += len(key[0])
        result[key[1]] = value()
        if pos < len(payload) and payload[pos] == ",":
            pos += 1
    return {"token": int(token) if token else None, "kind": kind, "name": name, "body": result}
