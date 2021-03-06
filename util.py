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



def to_snake(s):
    # Change the string into snake_case
    s = re.sub('[A-Z](?![A-Z0-9_]|$)', lambda m: '_' + m.group(0).lower(), s)
    s = re.sub('[A-Z]+', lambda m: '_' + m.group(0).lower() + '_', s)
    s = re.sub('_+', '_', s).strip('_')
    return s

def to_snake_upper(s):
    # Change the string into SNAKE_CASE
    return to_snake(s).upper()

def to_capitals(s):
    # Change the string into CamelCase
    s = re.sub(r'_([a-zA-Z])', lambda m: m.group(1).upper(), s)
    return s[0].upper() + s[1:]


# Reserved words in Crystal programming language
keywords = 'alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield BEGIN END'.split()

def unkeyword(s):
    # Add an underscore so the name is not a reserved word
    while s in keywords:
        s += '_'
    return s


def err(*args, **kwargs):
    # Print to stderr
    print(*args, file=sys.stderr, **kwargs)


def debug_source(path, line_start, line_end=None):
    # Output relevant source code
    with io.open(str(path)) as f:
        lines = list(enumerate(f, 1))
    real_line_end = line_end
    if line_end is None:
        line_end = line_start+4
        real_line_end = line_start
    return ''.join(
        str(i) + (':' if line_start <= i <= real_line_end else ' ') + '\t' + l
        for i, l in lines[line_start-1-1:line_end+1]
    ).strip('\n')

def debug_source_ast(ast):
    # Output relevant source code (determine file and lines from AST)
    lines = []
    class Visitor(pycparser.c_ast.NodeVisitor):
        def visit(self, node):
            if node.coord and node.coord.line:
                lines.append(node.coord.line)
            self.generic_visit(node)
    Visitor().visit(ast)
    return debug_source(ast.coord.file, min(lines), max(lines))


def parse_c(src):
    # Parse C source code into AST
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
    # Check if this source file is internal or part of the library
    if path in ['', '<built-in>']:
        return True
    try:
        return str(Path(path).relative_to(here/'pycparser'))
    except ValueError as e:
        return False


def debug_ast(node, top=True):
    # Pretty print an AST
    return '\n'.join(_debug_ast(node, not top))

def _debug_ast(node, skip=False):
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
            ind = ''
        else:
            yield rep
            ind = '    '
        attrs = ((k, getattr(node, k)) for k in node.attr_names)
        for key, val in itertools.chain(attrs, node.children()):
            lines = _debug_ast(val)
            yield ind + key + ': ' + next(lines)
            for line in lines:
                line = indent(line, ind)
                yield line
    else:
        yield repr(node)



def generate_c(ast):
    # Generate C code from AST
    if isinstance(ast, pycparser.c_ast.Node):
        return pycparser.c_generator.CGenerator().visit(ast)
    return ast


def indent(text, prefix):
    # Prepend prefix to every line of text
    return ''.join(prefix + line for line in text.splitlines(True))
