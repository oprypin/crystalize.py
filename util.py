from __future__ import print_function

import sys
import io
import re
import itertools
import textwrap
from pathlib import Path

try:
    script_name = __file__
except NameError:
    script_name = sys.argv[0]
here = Path(script_name).resolve().parent


sys.path.insert(0, str(here/'pycparser'))


import pycparser, pycparser.c_generator, pycparser.c_ast, pycparser.plyparser


def err(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def debug_source(path, line_start, line_end=None):
    with io.open(str(path)) as f:
        lines = list(enumerate(f, 1))
    if line_end is None:
        line_end = line_start+4
        real_line_end = line_start
    else:
        real_line_end = line_end
    return ''.join(
        str(i) + (':' if line_start <= i <= real_line_end else ' ') + '\t' + l
        for i, l in lines[line_start-1-1:line_end+1]
    ).strip('\n')

def debug_source_ast(ast):
    lines = []
    class Visitor(pycparser.c_ast.NodeVisitor):
        def visit(self, node):
            if node.coord and node.coord.line:
                lines.append(node.coord.line)
            self.generic_visit(node)
    Visitor().visit(ast)
    return debug_source(ast.coord.file, min(lines), max(lines))


def parse_c(src):
    try:
        return pycparser.CParser().parse(src)
    except pycparser.plyparser.ParseError as e:
        exc = e
    try:
        m = re.search(r'^(.+?):([0-9]+):[0-9]+:', str(exc))
        err(debug_source(m.group(1), int(m.group(2))))
    except Exception:
        pass
    raise pycparser.plyparser.ParseError(str(exc))


def internal(path):
    if path == '':
        return True
    try:
        return str(Path(path).relative_to(here/'pycparser'))
    except ValueError as e:
        return False


def _debug(node, skip=False):
    if isinstance(node, pycparser.c_ast.Node):
        rep = type(node).__name__
        if node.coord:
            if internal(node.coord.file):
                yield ''
                return
            rep += ' #{}'.format(node.coord.file)
            if node.coord.line:
                rep += ':{}'.format(node.coord.line)
        if skip:
            indent = ''
        else:
            yield rep
            indent = '    '
        attrs = ((k, getattr(node, k)) for k in node.attr_names)
        for key, val in itertools.chain(attrs, node.children()):
            lines = _debug(val)
            yield indent + key + ': ' + next(lines)
            for line in lines:
                line = textwrap.indent(line, indent)
                yield line
    else:
        yield repr(node)

def debug(node, top=True):
    return '\n'.join(_debug(node, not top))


def generate_c(ast):
    if isinstance(ast, pycparser.c_ast.Node):
        return pycparser.c_generator.CGenerator().visit(ast)
    return ast
