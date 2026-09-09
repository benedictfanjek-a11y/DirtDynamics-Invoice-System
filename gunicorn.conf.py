# Gunicorn loads this file automatically from the project root.
# Load the accounting routes only after Flask's app.py has been fully initialized.
preload_app = True

def post_worker_init(worker):
    try:
        import dd_accounts_loader  # noqa: F401
        worker.log.info("Dirt Dynamics accounting routes loaded successfully")
    except Exception:
        worker.log.exception("Dirt Dynamics accounting routes failed to load")
        raise
