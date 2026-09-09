# Reliable loader for the repaired Level 1 accounting extension.
from app import app
import dd_accounts_v2 as ext

def _register(endpoint, rule, func_name, methods=None):
    func=getattr(ext,func_name,None)
    if func is None: return False
    if endpoint in app.view_functions:
        app.view_functions[endpoint]=func; return True
    app.add_url_rule(rule,endpoint=endpoint,view_func=func,methods=methods or ['GET'])
    return True

_register('new_invoice','/invoice/new','new_invoice_v2',['GET','POST'])
_register('delete_invoice','/invoice/<int:iid>/delete','delete_invoice_v2',['POST'])
_register('edit_invoice','/invoice/<int:iid>/edit','edit_invoice',['GET','POST'])
_register('accounts','/accounts','accounts',['GET'])
_register('add_customer_payment','/accounts/customer','add_cp',['POST'])
_register('add_supplier_payment','/accounts/supplier','add_sp',['POST'])
_register('add_supplier','/accounts/supplier/add','add_supplier',['POST'])
_register('new_supplier_invoice','/accounts/purchase/new','new_purchase',['GET','POST'])
_register('delete_supplier_invoice','/accounts/purchase/<int:iid>/delete','delete_sp_invoice',['POST'])
_register('delete_customer_payment','/accounts/customer-payment/<int:pid>/delete','delete_cp',['POST'])
_register('delete_supplier_payment','/accounts/supplier-payment/<int:pid>/delete','delete_sp',['POST'])
_register('account_statement','/accounts/statement','statement',['GET'])
print('Dirt Dynamics accounting v2 routes registered successfully: /accounts')
