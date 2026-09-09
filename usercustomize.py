# Bootstrap the Dirt Dynamics sitecustomize extension after the base SQLite schema exists.
try:
    import app as _a
    _a.init_db()
    import sitecustomize as _sc
    import importlib
    importlib.reload(_sc)
except Exception:
    pass
