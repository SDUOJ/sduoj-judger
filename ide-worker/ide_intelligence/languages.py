"""Fixed language commands and HTTP result mappings."""

import os
from pathlib import Path
import shlex

def command(language: str, root: Path, shared=False):
    names = {
        "c": "AUTOLAB_IDE_CLANGD_COMMAND",
        "cpp": "AUTOLAB_IDE_CLANGD_COMMAND",
        "java": "AUTOLAB_IDE_JDTLS_COMMAND",
        "python": "AUTOLAB_IDE_PYRIGHT_COMMAND",
    }
    defaults = {
        "c": "clangd --background-index=false",
        "cpp": "clangd --background-index=false",
        "java": "jdtls",
        "python": "pyright-langserver --stdio",
    }
    raw = os.environ.get(names[language], defaults[language]).strip()
    command = shlex.split(raw) if raw else []
    if shared and language in {'c', 'cpp'} and command:
        from .resource_settings import integer
        controlled = {'--debug-origin', '--completion-style', '--completion-parse', '--header-insertion',
                      '--header-insertion-decorators', '--background-index', '--pch-storage', '-j'}
        command = [arg for arg in command if arg.split('=', 1)[0] not in controlled]
        command.extend(['--debug-origin', '--completion-style=detailed', '--completion-parse=always',
                        '--header-insertion=never', '--header-insertion-decorators=false',
                        '--background-index=false', '--pch-storage=memory',
                        '-j=' + str(integer('SDUOJ_IDE_CLANGD_JOBS', 2))])
    if shared and language == 'java' and command:
        from .resource_settings import integer
        processors = integer('SDUOJ_IDE_JAVA_PROCESSORS')
        heap = integer('SDUOJ_IDE_JAVA_HEAP_MB')
        if processors is not None:
            command.append('--jvm-arg=-XX:ActiveProcessorCount=' + str(processors))
        if heap is not None:
            command.append('--jvm-arg=-Xmx' + str(heap) + 'm')
    # JDTLS stores indexes and project state under its data directory. Give
    # every logical IDE session an isolated directory so concurrent Java
    # sessions never share mutable workspace state.
    if language == "java" and command and "-data" not in command:
        # Eclipse forbids a project location that contains its workspace data.
        # Keep both directories under the same disposable session directory.
        command.extend(["-data", str(root.parent / (root.name + "-jdtls-data"))])
    return command


def _completion_range(value):
    if not isinstance(value, dict):
        return None
    start, end = value.get('start', {}), value.get('end', {})
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    numbers = [start.get('line'), start.get('character'), end.get('line'), end.get('character')]
    if not all(type(n) is int and n >= 0 for n in numbers) or numbers[:2] > numbers[2:]:
        return None
    return dict(zip(('startLine', 'startColumn', 'endLine', 'endColumn'), (n + 1 for n in numbers)))


def normalize_completion(value):
    defaults = value.get('itemDefaults', {}) if isinstance(value, dict) else {}
    if not isinstance(defaults, dict):
        defaults = {}
    items = value.get('items', []) if isinstance(value, dict) else value or []
    if not isinstance(items, list):
        items = []
    result = []
    for item in items[:512]:
        if not isinstance(item, dict) or not isinstance(item.get('label'), str):
            continue
        row = {key: item[key] for key in ('label', 'kind', 'detail', 'documentation',
               'sortText', 'filterText', 'preselect', 'insertTextFormat', 'insertTextMode') if key in item}
        for key in ('insertTextFormat', 'insertTextMode'):
            if key not in row and key in defaults:
                row[key] = defaults[key]
        row['insertText'] = item.get('insertText', item['label'])
        edit = item.get('textEdit')
        if 'textEdit' in item:
            if not isinstance(edit, dict) or not isinstance(edit.get('newText'), str):
                continue
            row['insertText'] = edit['newText']
            ranges = edit
        else:
            ranges = defaults.get('editRange') or item.get('range')
            if ranges:
                row['insertText'] = item.get('textEditText', item['label'])
        if not isinstance(row['insertText'], str):
            continue
        characters = item.get('commitCharacters', defaults.get('commitCharacters'))
        if isinstance(characters, list):
            row['commitCharacters'] = list(dict.fromkeys(
                char for char in characters[:32] if isinstance(char, str)
                and len(char.encode('utf-16-le', errors='surrogatepass')) == 2
                and ord(char) >= 32 and not 0xd800 <= ord(char) <= 0xdfff))
        if isinstance(ranges, dict):
            if 'insert' in ranges or 'replace' in ranges:
                insert, replace = _completion_range(ranges.get('insert')), _completion_range(ranges.get('replace'))
                if not insert or not replace:
                    continue
                row.update(insertRange=insert, replaceRange=replace)
            else:
                normal = _completion_range(ranges.get('range', ranges))
                if not normal:
                    continue
                row['replaceRange'] = normal
        extra = item.get('additionalTextEdits', [])
        if not isinstance(extra, list) or len(extra) > 32:
            continue
        edits = []
        for entry in extra:
            # Only same-document edits. Commands, workspace edits and resolve data never leave the provider.
            edit_range = _completion_range(entry.get('range')) if isinstance(entry, dict) and 'uri' not in entry else None
            if not edit_range or not isinstance(entry.get('newText'), str):
                break
            edits.append({'range': edit_range, 'text': entry['newText']})
        else:
            if edits:
                row['additionalTextEdits'] = edits
            result.append(row)
    return {'isIncomplete': bool(value.get('isIncomplete', False)) if isinstance(value, dict) else False,
            'items': result}


def normalize_signature(value):
    if not isinstance(value, dict):
        return {'signatures': []}
    signatures = []
    for item in value.get('signatures', [])[:32]:
        if not isinstance(item, dict) or not isinstance(item.get('label'), str):
            continue
        row = {key: item[key] for key in ('label', 'documentation', 'activeParameter') if key in item}
        row['parameters'] = [
            {key: parameter[key] for key in ('label', 'documentation') if key in parameter}
            for parameter in item.get('parameters', [])[:128] if isinstance(parameter, dict)
        ]
        signatures.append(row)
    return {'signatures': signatures,
            'activeSignature': value.get('activeSignature', 0),
            'activeParameter': value.get('activeParameter', 0)}


def normalize_locations(value, source_uri: str, document_uri: str):
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    locations = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target = item.get("targetSelectionRange") or item.get("targetRange") or item.get("range")
        uri = item.get("targetUri") or item.get("uri")
        if not target or uri != source_uri:
            continue
        start, end = target.get("start", {}), target.get("end", {})
        locations.append({
            "documentUri": document_uri,
            "startLine": int(start.get("line", 0)) + 1,
            "startColumn": int(start.get("character", 0)) + 1,
            "endLine": int(end.get("line", 0)) + 1,
            "endColumn": int(end.get("character", 0)) + 1,
        })
    return locations


def normalize_diagnostics(value):
    result = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        start, end = item.get("range", {}).get("start", {}), item.get("range", {}).get("end", {})
        severity = {1: "error", 2: "warning", 3: "info", 4: "hint"}.get(item.get("severity"), "info")
        result.append({
            "source": "lsp",
            "severity": severity,
            "message": str(item.get("message", "")),
            "startLine": int(start.get("line", 0)) + 1,
            "startColumn": int(start.get("character", 0)) + 1,
            "endLine": int(end.get("line", 0)) + 1,
            "endColumn": int(end.get("character", 0)) + 1,
            "code": str(item.get("code")) if item.get("code") is not None else None,
        })
    return [{key: value for key, value in row.items() if value is not None} for row in result]
