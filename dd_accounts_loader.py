# Reliable loader for the repaired Level 1 accounting extension.
from app import app
import dd_accounts_v2 as ext
import dd_supplier_edit as supplier_edit
import dd_inventory_stock as inventory_stock
import dd_dashboard_invoices as dashboard_invoices
import dd_tasks as tasks


def _register(endpoint, rule, func_name, methods=None, module=None):
    source = module or ext
    func = getattr(source, func_name, None)
    if func is None:
        print(f"Dirt Dynamics route skipped: {endpoint} ({func_name} not found)")
        return False
    has_rule = any(r.endpoint == endpoint for r in app.url_map.iter_rules())
    if not has_rule:
        app.add_url_rule(rule, endpoint=endpoint, view_func=func, methods=methods or ['GET'])
    else:
        app.view_functions[endpoint] = func
    return True


_register('new_invoice', '/invoice/new', 'new_invoice_v2', ['GET', 'POST'])
# Dashboard invoice deletion is permanent and restores stock.
_register('delete_invoice', '/invoice/<int:iid>/delete', 'delete_invoice', ['POST'], dashboard_invoices)
_register('edit_invoice', '/invoice/<int:iid>/edit', 'edit_invoice', ['GET', 'POST'])
_register('accounts', '/accounts', 'accounts', ['GET'])
_register('add_customer_payment', '/accounts/customer', 'add_cp', ['POST'])
_register('add_supplier_payment', '/accounts/supplier', 'add_sp', ['POST'])
_register('add_supplier', '/accounts/supplier/add', 'add_supplier', ['POST'])
_register('new_supplier_invoice', '/accounts/purchase/new', 'new_purchase', ['GET', 'POST'])
_register('edit_supplier_invoice', '/accounts/purchase/<int:iid>/edit', 'edit_supplier_invoice', ['GET', 'POST'], supplier_edit)
_register('delete_supplier_invoice', '/accounts/purchase/<int:iid>/delete', 'delete_sp_invoice', ['POST'])
_register('delete_customer_payment', '/accounts/customer-payment/<int:pid>/delete', 'delete_cp', ['POST'])
_register('delete_supplier_payment', '/accounts/supplier-payment/<int:pid>/delete', 'delete_sp', ['POST'])
_register('account_statement', '/accounts/statement', 'statement', ['GET'])

# Replace the dashboard view so its invoice tile counts only invoices still saved.
_register('dashboard', '/', 'dashboard', ['GET'], dashboard_invoices)

# Inventory stock controls. dd_inventory_stock creates the qty column and
# registers the edit and stock-adjustment routes when imported.
_register('edit_item', '/item/<int:item_id>/edit', 'edit_item', ['GET', 'POST'], inventory_stock)
_register('adjust_stock', '/item/<int:item_id>/stock', 'adjust_stock', ['POST'], inventory_stock)

# Employee task management. Tasks live under Employees and are also shown
# in each employee's existing portal.
_register('employee_tasks', '/employees/tasks', 'employee_tasks', ['GET'], tasks)
_register('employee_task_add', '/employees/tasks/add', 'employee_task_add', ['POST'], tasks)
_register('employee_task_edit', '/employees/tasks/<int:task_id>/edit', 'employee_task_edit', ['GET', 'POST'], tasks)
_register('employee_task_delete', '/employees/tasks/<int:task_id>/delete', 'employee_task_delete', ['POST'], tasks)
_register('employee_task_toggle', '/employee/tasks/<int:task_id>/toggle', 'employee_task_toggle', ['POST'], tasks)

print('Dirt Dynamics accounting v2 routes registered successfully: /accounts')
print('Dirt Dynamics inventory stock controls registered successfully: /item/<item_id>/stock')
print('Dirt Dynamics dashboard invoice controls registered successfully: permanent delete + saved count')
print('Dirt Dynamics employee task controls registered successfully: /employees/tasks')
