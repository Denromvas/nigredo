#!/usr/bin/env python3
"""Генерує граматику TextMate для Nigredo з таблиці гліфів інтерпретатора (щоб підсвітка не розходилася з мовою).
    python3 editors/vscode/build.py"""
import importlib.util
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('nigredo', HERE.parent.parent / 'interpreter' / 'nigredo.py')
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)

special = '🜂🜁🜔λΛ←※「」〔〕【】『』《》¦¯'
ops = ''.join(g for g in N.GLYPHS if len(g) == 1 and g not in special)
consts = ''.join(getattr(N, 'CONSTS', '●○∅'))
cls = lambda s: '[' + ''.join(re.escape(c) for c in s) + ']'   # noqa: E731

grammar = {
    '$schema': 'https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json',
    'name': 'Nigredo', 'scopeName': 'source.nigredo', 'fileTypes': ['ngr'],
    'patterns': [{'include': '#comment'}, {'include': '#seal'}, {'include': '#deleg'}, {'include': '#tool'},
                 {'include': '#string'}, {'include': '#template'}, {'include': '#lambda'}, {'include': '#bind'},
                 {'include': '#number'}, {'include': '#const'}, {'include': '#op'}, {'include': '#bracket'}],
    'repository': {
        'comment': {'name': 'comment.line.nigredo', 'match': '※.*$'},
        'seal': {'name': 'keyword.control.seal.nigredo', 'match': '🜂'},
        'deleg': {'name': 'keyword.control.subagent.nigredo', 'match': '🜁'},
        'tool': {'match': r'(🜔)([^\s「」【】『』《》〔〕]+)',
                 'captures': {'1': {'name': 'keyword.control.tool.nigredo'}, '2': {'name': 'entity.name.function.tool.nigredo'}}},
        'string': {'name': 'string.quoted.nigredo', 'begin': '「', 'end': '」',
                   'patterns': [{'name': 'constant.character.escape.nigredo', 'match': r'\\.'}]},
        'template': {'name': 'string.template.nigredo', 'begin': '〔', 'end': '〕',
                     'patterns': [{'name': 'constant.character.escape.nigredo', 'match': r'\\.'},
                                  {'name': 'meta.embedded.expression.nigredo', 'begin': r'\{', 'end': r'\}',
                                   'beginCaptures': {'0': {'name': 'punctuation.section.embedded.nigredo'}},
                                   'endCaptures': {'0': {'name': 'punctuation.section.embedded.nigredo'}},
                                   'patterns': [{'include': '$self'}]}]},
        'lambda': {'name': 'storage.type.function.nigredo', 'match': '[λΛ]'},
        'bind': {'match': r'(←)\s*([^\s「」【】『』《》〔〕]+)',
                 'captures': {'1': {'name': 'keyword.operator.assignment.nigredo'}, '2': {'name': 'variable.other.definition.nigredo'}}},
        'number': {'name': 'constant.numeric.nigredo', 'match': r'¯?\d+(\.\d+)?'},
        'const': {'name': 'constant.language.nigredo', 'match': cls(consts)},
        'op': {'name': 'keyword.operator.glyph.nigredo', 'match': cls(ops) + '|¦'},
        'bracket': {'name': 'punctuation.section.nigredo', 'match': '[【】『』《》]'},
    },
}
(HERE / 'syntaxes' / 'nigredo.tmLanguage.json').write_text(json.dumps(grammar, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print(f'гліфів-операторів: {len(ops)}, сталих: {len(consts)}')
