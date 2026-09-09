# Gunicorn loads this file automatically from the project root.
# The accounting extension must be imported only after app.py has fully initialized.
preload_app = True

def post_worker_init(worker):
    try:
        import dd_accounts  # noqa: F401
        worker.log.info("Dirt Dynamics accounting extension loaded successfully")
    except Exception:
        worker.log.exception("Dirt Dynamics accounting extension failed to load")
        raise
