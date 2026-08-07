# Exists solely to put the repository root on sys.path, so `mcp_server/tests` can import
# `mcp_server.tools` as a package. pytest's default (prepend) import mode inserts the first
# ancestor directory without an __init__.py - for mcp_server/tests/test_tools.py that's
# mcp_server/tests itself, which doesn't make `mcp_server` importable. A conftest.py is imported
# the same way, so placing one here inserts the root instead.
#
# Same trick, same reason as the empty functions/conftest.py (which puts functions/ on the path
# for `from shared...` imports). Without it, only `python -m pytest` works - that form adds the
# working directory to sys.path itself, which is why this gap survived until CI ran plain
# `pytest` and the README's documented command turned out to be broken too.
