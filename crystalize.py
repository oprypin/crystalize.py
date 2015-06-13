#!/usr/bin/env python

import sys
import os
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



# Path to the header file is the first command line argument
header = Path(sys.argv[1])
try:
    # Include path is the second command line argument
    root = Path(sys.argv[2])
except IndexError:
    # Or detect it automatically by searching upwards for a directory named 'include'
    root = header.parent
    if 'include' in root.parts:
        while root.name != 'include':
            root = root.parent
header = header.relative_to(root)

os.chdir(str(root))


err("================ Preprocessing =================")
# Call GCC preprocessor
proc = subprocess.Popen(['gcc', '-E',
    '-undef',    # Do not predefine any system-specific or GCC-specific macros
    '-dD',       # Dump all macro definitions, at the end of preprocessing, in addition to normal output
    '-nostdinc', # Do not search the standard system directories for header files
    '-I{}'.format(here/'pycparser'/'utils'/'fake_libc_include'), # Add pycparser's fake headers
    '-I{}'.format(root),
    str(header)
], stdout=subprocess.PIPE, universal_newlines=True)
src = proc.communicate()[0] # Get stdout


# Hack to change all defines into fake constants, so they can be parsed later by pycparser
# First we need a fake type to distinguish them
src = '''
typedef int _DEFINE;
''' + src
# Replace macros without arguments with consts
src = re.sub(r'^#define ([a-zA-Z_][_a-zA-Z_0-9]*) ([^\n"]+)$', r'const _DEFINE \1 = "\2";', src, flags=re.MULTILINE)
# Discard the rest
src = re.sub(r'^#define.*$', r'', src, flags=re.MULTILINE)

# Uncomment to print the code that will be passed to pycparser
#err(src)


err("=================== Parsing ====================")
ast = parse_c(src)

# Uncomment to print the abstract syntax tree produced by pycparser
#err(debug(ast, False))



# Convenience import to get all the node classes in the namespace
from pycparser.c_ast import *

err("================= Transforming =================")

# Accumulate code that will be inside the lib statement...
lib_code = []
# and after it
code = []

# `lib ...`
lib_name = 'Lib'


# The `rename_` functions accept names that are present in C and return the names that will be used in Crystal code

# Used for variables, arguments, members.
def rename_identifier(name):
    return unkeyword(to_snake(name))

# Used for constants
def rename_const(name):
    return unkeyword(to_snake_upper(name))

# Used for functions
def rename_func(name):
    return rename_identifier(name)

# Detects native types and returns their analog in Crystal, or None if it is not a native type
def native_type(name):
    for match, repl in {
        r'_*([Uu]?)[Ii]nt([1-9][0-9]*).*': lambda m: m.group(1).upper() + 'Int' + m.group(2), # [U]IntXX
        r'_*[Ff]loat([1-9][0-9]*).*': lambda m: 'Float' + m.group(1), # FloatXX
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
        m = re.search('^(?:'+match+')$', name)
        if m:
            if isinstance(repl, str):
                return repl
            else:
                return repl(m)

def rename_type(name, lib=None):
    return unkeyword(native_type(name) or to_capitals(name))

# Counter used to name anonymous structs
anonymous_counter = 0
def anon():
    global anonymous_counter
    anonymous_counter += 1
    return anonymous_counter

# Recursively turn a type's AST into a Crystal type string
# This is used for "inline" types, such as variable's type or struct member's type, and not for top-level declarations.
def make_type(type):
    # If it's a pointer type
    if isinstance(type, PtrDecl):
        # If it's a function pointer
        if isinstance(type.type, FuncDecl):
            # Handle the function declaration in another call
            return make_type(type.type)
        # Make the rest of the type and add a star at the end, unless it's a Void*-type
        result = make_type(type.type)
        if result not in pointer_types:
            result += '*'
        return result
    
    # If it's an array type
    if isinstance(type, ArrayDecl):
        # Make the rest of the type and add brackets at the end, with the value
        # The value is typically a number, but could be any C code
        # We just generate C and hope it will be valid Crystal code
        if type.dim:
            return '{}[{}]'.format(make_type(type.type), generate_c(type.dim.value))
        else:
            # Array without specified dimension
            return '{}*'.format(make_type(type.type))
    
    # If it's a function type
    if isinstance(type, FuncDecl):
        func = type
        func_type = make_type(func.type)
        # Turn each argument AST into an name:type pair and get just the type
        # Caveats: func.args may be None; arg may be void due to simplistic parsing of function without arguments
        func_args = [make_arg(arg).type for arg in func.args.params if make_arg(arg)] if func.args else []
        # Form a template (no parentheses needed for 1 arg, skip altogether for 0 args)
        fmt = ('({args}) -> {type}' if len(func_args) > 1 else '{args} -> {type}') if func_args else '-> {type}'
        # Fill the template with list of args and return type
        return fmt.format(args=', '.join(func_args), type=func_type)
    
    # If it's a misc type declaration
    if isinstance(type, TypeDecl):
        # If it's a struct
        if isinstance(type.type, Struct) and type.type.decls:
            # This will be a struct inside a struct, typically anonymous
            struct = type.type
            # Get the struct's name or generate one
            struct_name = struct.name or 'Anonymous{}'.format(anon())
            output = []
            output.append('struct {}'.format(rename_type(struct_name)))
            for decl in struct.decls:
                member = make_member(decl)
                output.append('  {} : {}'.format(member.name, member.type))
            output.append('end')
            # Immediately add the struct to the lib, and return just its name
            # This unfolds nested structs
            lib_code.append('\n'.join(output))
            return rename_type(struct_name)
        # If it's just some normal type, which might consist of multiple components
        try:
            return rename_type(' '.join(type.type.names))
        except AttributeError:
            return rename_type(type.type.name)
    
    # Don't know what this is. Just paste the C code
    return generate_c(type)

# Storage class for a function argument, struct member, etc
class Item(collections.namedtuple('Item', 'name type')):
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
        return Item(name=None, type=make_type(arg.type))
    return Item(
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
            cr_output.append(indent(src, '  # '))
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
            if union.decls:
                output.append('union {}'.format(rename_type(union_name)))
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
print(indent('\n\n'.join(lib_code), '  '))
print('end')
if code:
    print('')
    print('\n\n'.join(code))
