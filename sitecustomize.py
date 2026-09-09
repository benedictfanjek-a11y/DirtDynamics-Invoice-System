# Load the inventory extension during Python startup so gunicorn app:app gets
# the stock migration and inventory routes before the first request.
try:
    import dd_inventory_stock  # noqa: F401
except Exception as exc:
    print(f"Dirt Dynamics inventory extension failed to load: {exc}")
