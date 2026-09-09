# Reliable loader for the Level 1 accounting extension.
# dd_accounts contains the accounting views, but its legacy inventory hooks can
# fail before those views are registered. This loader imports the module after
# app.py is initialized and registers the accounting views that are available.

from app import app
import dd_accounts as ext


def _register(endpoint, rule, func_name, methods=None):
    func = getattr(ext, func_name, None)
    if func is None:
        return False
    if endpoint in app.view_functions:
        app.view_functions[endpoint] = func
        return True
    kwargs = {}
    if methods:
        kwargs["methods"] = methods
    app.add_url_rule(rule, endpoint=endpoint, view_func=func, **kwargs)
    return True


# Replace the existing invoice creation/deletion handlers with the quantity-aware versions.
if getattr(ext, "new_invoice_v2", None) is not None:
    app.view_functions["new_invoice"] = ext.new_invoice_v2
if getattr(ext, "delete_invoice", None) is not None:
    app.view_functions["delete_invoice"] = ext.delete_invoice

_register("edit_invoice", "/invoice/<int:iid>/edit", "edit_invoice", ["GET", "POST"])
_register("accounts", "/accounts", "accounts", ["GET"])
_register("add_customer_payment", "/accounts/customer", "add_cp", ["POST"])
_register("add_supplier_payment", "/accounts/supplier", "add_sp", ["POST"])
_register("add_supplier", "/accounts/supplier/add", "add_supplier", ["POST"])
_register("new_supplier_invoice", "/accounts/purchase/new", "new_purchase", ["GET", "POST"])
_register("delete_supplier_invoice", "/accounts/purchase/<int:iid>/delete", "delete_sp_invoice", ["POST"])
_register("delete_customer_payment", "/accounts/customer-payment/<int:pid>/delete", "delete_cp", ["POST"])
_register("delete_supplier_payment", "/accounts/supplier-payment/<int:pid>/delete", "delete_sp", ["POST"])
_register("account_statement", "/accounts/statement", "statement", ["GET"])

# Make the successful load unmistakable in Render logs.
print("Dirt Dynamics accounting routes registered successfully:", "/accounts" in [r.rule for r in app.url_map.iter_rules()])
