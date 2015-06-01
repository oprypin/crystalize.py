#!/usr/bin/env python

import sys
import io
import os, os.path
import re
import textwrap
import collections
import subprocess
from pathlib import Path

from util import *

import pycparser

# Generate lextab, yacctab
pycparser.CParser().parse('', '')
try:
    for f in ['lextab.py', 'yacctab.py']:
        (here/f).rename(here/'pycparser'/'pycparser'/f)
except Exception as e: pass


try:
    textwrap.indent
except AttributeError:
    def indent(text, prefix):
        return ''.join(prefix + line for line in text.splitlines(True))
    textwrap.indent = indent


header = Path(sys.argv[1])
try:
    root = Path(sys.argv[2])
except IndexError:
    root = header.parent
    if 'include' in root.parts:
        while root.name != 'include':
            root = root.parent
header = header.relative_to(root)

os.chdir(str(root))


err("================ Preprocessing =================")
proc = subprocess.Popen(['gcc', '-E',
    '-dD', '-undef', '-nostdinc',
    '-I{}'.format(here/'pycparser'/'utils'/'fake_libc_include'),
    '-I{}'.format(root),
    str(header)
], stdout=subprocess.PIPE, universal_newlines=True)
src = proc.communicate()[0]


src = '''
typedef int _DEFINE;
''' + src
src = re.sub(r'^#define ([a-zA-Z_][_a-zA-Z_0-9]*) ([^\n"]+)$', r'const _DEFINE \1 = "\2";', src, flags=re.MULTILINE)
src = re.sub(r'^#define.*$', r'', src, flags=re.MULTILINE)
# err(src)


err("=================== Parsing ====================")
ast = parse_c(src)
# err(debug(ast, False))




from pycparser.c_ast import *

err("================= Transforming =================")

lib_code = []
code = []

keywords = 'alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield BEGIN END'.split()

lib_name = 'Lib'

def rename_identifier(name):
    name = re.sub('[A-Z](?![A-Z0-9_]|$)', lambda m: '_' + m.group(0).lower(), name)
    name = re.sub('[A-Z]+', lambda m: '_' + m.group(0).lower() + '_', name)
    name = re.sub('_+', '_', name).strip('_')
    if name in keywords:
        name += '_'
    return name

def rename_const(name):
    return rename_identifier(name).upper()

def rename_func(name):
    return rename_identifier(name)

def native_type(type):
    for match, repl in {
        r'_*([Uu]?)[Ii]nt([1-9][0-9]*).*': lambda m: m.group(1).upper() + 'Int' + m.group(2),
        r'_*[Ff]loat([1-9][0-9]*).*': lambda m: 'Float' + m.group(1),
        'signed char': 'Int8',
        '(unsigned )?char': 'UInt8',
        '(signed )?short( int)?': 'Int16',
        'unsigned short( int)?': 'UInt16',
        '(signed )?int': 'Int32',
        'unsigned( int)?': 'UInt32',
        '(signed )?long( int)?': 'LibC::LongT',
        'unsigned long( int)?': 'LibC::LongT',
        '(signed )?long long( int)?': 'Int64',
        'unsigned long long( int)?': 'UInt64',
        'float': 'Float32',
        '(long )?double': 'Float64',
        'size_t|uintptr_t': 'LibC::SizeT',
    }.items():
        m = re.search('^(?:'+match+')$', type)
        if m:
            if isinstance(repl, str):
                return repl
            else:
                return repl(m)

def rename_type(type, lib=None):
    r = native_type(type)
    if r:
        return r
    type = re.sub(r'_([a-zA-Z])', lambda m: m.group(1).upper(), type)
    return type[0].upper() + type[1:]

anonymous_counter = 0
def anon():
    global anonymous_counter
    anonymous_counter += 1
    return anonymous_counter

def make_type(type):
    if isinstance(type, PtrDecl):
        if isinstance(type.type, FuncDecl):
            return make_type(type.type)
        result = make_type(type.type)
        if result not in pointer_types:
            result += '*'
        return result
    
    if isinstance(type, ArrayDecl):
        return '{}[{}]'.format(make_type(type.type), generate_c(type.dim.value))
    
    if isinstance(type, FuncDecl):
        func = type
        func_type = make_type(func.type)
        func_args = [make_arg(arg).type for arg in func.args.params if make_arg(arg)] if func.args else []
        if func_args:
            return '({}) -> {}'.format(', '.join(func_args), func_type)
        else:
            return '-> {}'.format(func_type)
    
    if isinstance(type, TypeDecl):
        if isinstance(type.type, Struct) and type.type.decls:
            struct = type.type
            struct_name = struct.name or 'Anonymous{}'.format(anon())
            output = []
            output.append('struct {}'.format(rename_type(struct_name)))
            for decl in struct.decls:
                member = make_member(decl)
                output.append('  {} : {}'.format(member.name, member.type))
            output.append('end')
            lib_code.append('\n'.join(output))
            return rename_type(struct_name)
        try:
            return rename_type(' '.join(type.type.names))
        except AttributeError:
            return rename_type(type.type.name)
    
    return generate_c(type)

class Argument(collections.namedtuple('Argument', 'name type')):
    def __str__(self):
        if self.name:
            return '{} : {}'.format(self.name, self.type)
        else:
            return self.type
def make_arg(arg):
    if isinstance(arg, EllipsisParam):
        return '...'
    if isinstance(arg, Typename):
        try:
            if arg.type.type.names == ['void']:
                return None
        except AttributeError:
            pass
        return Argument(name=None, type=make_type(arg.type))
    return Argument(
        name=rename_identifier(arg.name) if arg.name else None,
        type=make_type(arg.type)
    )
def make_member(member):
    return make_arg(member)

pointer_types = set()

for top in ast.ext:
    try:
        output = []
        
        if top.coord and internal(top.coord.file):
            continue
        
        if isinstance(top, Decl) and isinstance(top.type, FuncDecl):
            func = top.type
            func_name = top.name
            func_args = [make_arg(arg) for arg in func.args.params if make_arg(arg)] if func.args else []
            if func_args == [None]:
                func_args = []
            func_type = make_type(func.type)
            
            output.append('fun {} = "{}"({}) : {}'.format(
                rename_func(func_name), func_name,
                ', '.join(str(arg) for arg in func_args),
                func_type
            ))
        
        elif isinstance(top, FuncDef):
            decl, body = top.decl, top.body
            func = decl.type
            func_name = decl.name
            func_args = [make_arg(arg) for arg in func.args.params if make_arg(arg)] if func.args else []
            if func_args == [None]:
                func_args = []
            func_type = make_type(func.type)
            
            cr_output = []
            cr_output.append('def {}({}) : {}'.format(
                rename_func(func_name),
                ', '.join(
                    '{} : {}::{}'.format(arg.name, lib_name, arg.type)
                    for arg in func_args
                ),
                func_type
            ))
            src = generate_c(body).strip('\n')
            if src.startswith('{') and src.endswith('}'):
                src = textwrap.dedent(src[1:-1].strip('\n'))
            src = re.sub(r'\n+', r'\n', src)
            cr_output.append(textwrap.indent(src, '  # '))
            cr_output.append('end')
            code.append('\n'.join(cr_output))
        
        elif isinstance(top, Decl) and isinstance(top.type, Struct) or\
          isinstance(top, Typedef) and isinstance(top.type.type, Struct):
            if isinstance(top, Decl):
                struct, struct_name = top.type, top.type.name
            else:
                struct, struct_name = top.type.type, top.name
            if struct.decls:
                output.append('struct {}'.format(rename_type(struct_name)))
                for decl in struct.decls:
                    member = make_member(decl)
                    output.append('  {} : {}'.format(member.name, member.type))
                output.append('end')
            else:
                output.append('type {} = Void*'.format(rename_type(struct_name)))
                pointer_types.add(rename_type(struct_name))
        
        elif isinstance(top, Decl) and isinstance(top.type, Enum) or\
          isinstance(top, Typedef) and isinstance(top.type.type, Enum):
            if isinstance(top, Decl):
                enum, enum_name = top.type, top.type.name
            else:
                enum, enum_name = top.type.type, top.name
            if enum_name:
                output.append('enum {}'.format(rename_type(enum_name)))
                for item in enum.values.enumerators:
                    if item.value:
                        output.append('  {} = {}'.format(rename_const(item.name), generate_c(item.value)))
                    else:
                        output.append('  {}'.format(rename_const(item.name)))
                output.append('end')
            else:
                for item in enum.values.enumerators:
                    output.append('  {} = {}'.format(rename_const(item.name), generate_c(item.value)))
        
        elif isinstance(top, Decl) and isinstance(top.type, Union) or\
          isinstance(top, Typedef) and isinstance(top.type.type, Union):
            if isinstance(top, Decl):
                union, union_name = top.type, top.type.name
            else:
                union, union_name = top.type.type, top.name
            output.append('union {}'.format(rename_type(struct_name)))
            for decl in union.decls:
                member = make_member(decl)
                output.append('  {} : {}'.format(rename_identifier(member.name), member.type))
            output.append('end')

        elif isinstance(top, Typedef):
            output.append('alias {} = {}'.format(rename_type(top.name), make_type(top.type)))
        
        elif isinstance(top, Decl) and top.quals == ['const']:
            val = generate_c(top.init)
            if top.init:
                output.append('{} = {}'.format(rename_const(top.name), val.strip('"')))
            else:
                output.append('#{} ='.format(rename_const(top.name)))
        
        elif isinstance(top, Decl):
            output.append('${} : {}'.format(rename_identifier(top.name), make_type(top.type)))
        
        else:
            raise Exception("Unknown")
        
        if output:
            lib_code.append('\n'.join(output))
    except Exception as e:
        err(debug(top))
        err(debug_source_ast(top))
        raise


print('lib {}'.format(lib_name))
print(textwrap.indent('\n\n'.join(lib_code), '  '))
print('end')
if code:
    print('')
    print('\n\n'.join(code))
