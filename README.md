crystalize.py
=============

This is a Python script that generates `lib` definitions in [Crystal](http://crystal-lang.org/) programming language based on C header files.

Requires Python 3.4+ and `gcc` in PATH.  
Also supports Python 3.3 and 2.7 if [pathlib](https://pypi.python.org/pypi/pathlib/) is installed.  
A dependency, [pycparser](https://pypi.python.org/pypi/pycparser/2.13), is included as a submodule.

Installation: install dependencies, `git clone --recursive`

Usage: `./crystalize.py path/to/header.h > output.cr`

Configuration: edit the script itself. Even the most intricate config file cannot replace editing the code.


Very few libraries will work without manually modifying the result, but almost all the tedious work is done automatically.

Supports the following top-level declarations:

- Function declarations &rarr; `fun`
- Structs (incl. nested) &rarr; `struct`
- Enums &rarr; `enum`
- Unions &rarr; `union`
- Typedefs &rarr; `alias`
- Constants &rarr; `CONSTANT = ...`
- Variables &rarr; `$var = ...`
- Macros &rarr; `CONSTANT = ...`; can be problematic
- Function definitions &rarr; `def`; just dumps C code as the function's body

---

## [Examples of generated libraries](https://gist.github.com/e4e005e68ca88ea3240f)
