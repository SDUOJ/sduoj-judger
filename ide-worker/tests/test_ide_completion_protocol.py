import asyncio
from pathlib import Path

from ide_intelligence.languages import normalize_completion, normalize_signature
from ide_intelligence.lsp_process import LspProcess


def rng(start=0, end=3, line=0):
    return {'start': {'line': line, 'character': start}, 'end': {'line': line, 'character': end}}


def test_completion_preserves_defaults_insert_replace_filter_and_snippets():
    result = normalize_completion({'isIncomplete': True, 'itemDefaults': {
        'insertTextFormat': 2, 'editRange': {'insert': rng(), 'replace': rng(end=5)}},
        'items': [{'label': 'print(…)', 'filterText': 'print', 'preselect': True,
                   'textEditText': 'print(${1:value})', 'kind': 3, 'command': {'command': 'unsafe'},
                   'data': {'uri': 'file:///other-user.py'}}]})
    item = result['items'][0]
    assert result['isIncomplete'] and item['filterText'] == 'print'
    assert item['insertTextFormat'] == 2 and item['preselect']
    assert item['insertText'] == 'print(${1:value})'
    assert item['insertRange']['endColumn'] == 4 and item['replaceRange']['endColumn'] == 6
    assert 'command' not in item and 'data' not in item


def test_completion_never_coerces_invalid_or_cross_file_edits_to_first_line():
    for edit in ({'newText': 'x'}, {'range': rng(-1), 'newText': 'x'}):
        assert normalize_completion([{'label': 'x', 'textEdit': edit}])['items'] == []
    assert normalize_completion([{'label': 'x', 'additionalTextEdits': [
        {'uri': 'file:///another.py', 'range': rng(), 'newText': 'BAD'}]}])['items'] == []
    item = normalize_completion([{'label': 'x', 'additionalTextEdits': [
        {'range': rng(0, 0), 'newText': 'import x\n'}]}])['items'][0]
    assert item['additionalTextEdits'][0]['range']['startColumn'] == 1
    assert 'replaceRange' not in item


def test_signature_preserves_parameter_label_offsets_and_plain_docs():
    result = normalize_signature({'signatures': [{'label': 'f(value: int)', 'parameters': [
        {'label': [2, 12], 'documentation': 'value docs'}]}], 'activeParameter': 0})
    assert result['signatures'][0]['parameters'][0]['label'] == [2, 12]
    assert normalize_signature(None) == {'signatures': []}


def test_completion_empty_insertions_and_default_edit_text_follow_lsp_precedence():
    assert normalize_completion([{'label': 'erase', 'insertText': ''}])['items'][0]['insertText'] == ''
    result = normalize_completion({'itemDefaults': {'editRange': rng()}, 'items': [
        {'label': 'label', 'insertText': 'ignored'},
        {'label': 'erase', 'textEditText': ''},
        {'label': 'explicit', 'textEditText': 'ignored',
         'textEdit': {'range': rng(), 'newText': ''}}]})
    assert [item['insertText'] for item in result['items']] == ['label', '', '']


def test_completion_commit_character_defaults_allow_explicit_empty_override():
    result = normalize_completion({'itemDefaults': {'commitCharacters': ['.', '.', '(', 'xx', '\n', 3, '😀']},
        'items': [{'label': 'default'}, {'label': 'disabled', 'commitCharacters': []},
                  {'label': 'custom', 'commitCharacters': [')']}]})
    assert [item['commitCharacters'] for item in result['items']] == [['.', '('], [], [')']]


def test_malformed_completion_results_degrade_without_invalid_edits():
    assert normalize_completion({'items': None})['items'] == []
    assert normalize_completion({'items': {}, 'itemDefaults': None})['items'] == []
    for edit in (None, {}, {'range': rng()}, {'range': {'start': None, 'end': {}} , 'newText': 'x'}):
        assert normalize_completion([{'label': 'x', 'textEdit': edit}])['items'] == []


def test_shared_signature_uses_own_document_and_strips_index_documentation():
    async def run():
        process = LspProcess([], Path('/tmp/ide-protocol-test'), None, 'cpp')
        process._documents['own'] = {'uri': 'file:///own/main.cpp', 'line_offset': 4}
        recorded = []
        async def request(method, params):
            recorded.append((method, params))
            return {'signatures': [{'label': 'f(int own)', 'documentation': 'private index doc',
                    'parameters': [{'label': 'int own', 'documentation': 'private param doc'}]}]}
        process.request = request
        result = await process.signature_for('own', 2, 3)
        assert recorded[0] == ('textDocument/signatureHelp', {
            'textDocument': {'uri': 'file:///own/main.cpp'}, 'position': {'line': 5, 'character': 2}})
        assert 'documentation' not in result['signatures'][0]
        assert 'documentation' not in result['signatures'][0]['parameters'][0]
    asyncio.run(run())
