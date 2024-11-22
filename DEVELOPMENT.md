# Documentation and notes for developers

## Python project configuration

All configuration for the tools used by your IDE is done in [./pyproject.toml].

### Pyright

We use [basedpyright](https://docs.basedpyright.com/latest/) as a type checker.
The primary purpose is to ensure that the code we write does not make assumptions that cannot be proven to be correct.
As an example, this will help remind us to check if a value can be `None` or if it has not been bound yet.
It will also help to prevent us trying to access fields on objects that do not exist.

### Ruff

We use [ruff](https://docs.astral.sh/ruff/) as our formatter and linter.
This ensures our code is formatted consistently and in a way that is easy to read.
It will also be able to catch some mistakes and bad practices in our code.
E.g. `x == None` instead of `x is None`.

## Typings for the environment

We have a folder for all the modules that live in klippy that we make use of.
Inside [./typings] is a file named after the module with some dummy classes.
These are the modules that our code will be checked against when pyright is executed.
We can improve our confidence by ensuring these are well defined and up to date with the actual code.
The files that we import with `from . import probe` are reexported in [./__init__.py] to allow pyright to infer this.

## Testing changes

A convenience macro, [./cartographer_ci_test.cfg], has been made to help us test changes.
This can be linked into your `printer_data/configs` and included in `printer.cfg` for ease of use.
We should strive to keep this up to date.
