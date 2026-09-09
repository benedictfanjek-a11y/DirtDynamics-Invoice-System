# Supplier invoice editing extension. Loaded after app.py by dd_accounts_loader.py.
from datetime import date
from flask import render_template, request, redirect, url_for, flash
import app as _a


def _stotal(c, iid):
    inv = c.execute('SELECT discount,vat_rate FROM supplier_invoices WHERE id=?', (iid,)).fetchone()
    lines = c.execute('SELECT qty,unit_price FROM supplier_invoice_lines WHERE supplier_invoice_id=?', (iid,)).fetchall()
    sub = sum(float(r['qty']) * float(r['unit_price']) for r in lines)
    discount = min(max(0, float(inv['discount'] or 0)), sub)
    taxable = max(0, sub - discount)
    return taxable + taxable * float(inv['vat_rate'] or 0) / 100


def edit_supplier_invoice():
    iid = int(request.view_args['iid'])
    c = _a.db()
    inv = c.execute('SELECT * FROM supplier_invoices WHERE id=? AND COALESCE(deleted,0)=0', (iid,)).fetchone()
    if not inv:
        c.close()
        return 'Supplier invoice not found', 404

    if request.method == 'POST':
        try:
            paid = float(c.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_invoice_id=?', (iid,)).fetchone()[0])
            if paid > 0:
                raise ValueError('This supplier invoice has payments. Reverse the supplier payment(s) in Accounts before editing the invoice.')

            # Return the old purchase quantities to stock before replacing the lines.
            old_lines = c.execute('SELECT item_id,qty FROM supplier_invoice_lines WHERE supplier_invoice_id=?', (iid,)).fetchall()
            for l in old_lines:
                if l['item_id']:
                    c.execute('UPDATE items SET qty=COALESCE(qty,0)+?, active=1 WHERE id=?', (float(l['qty']), l['item_id']))

            c.execute('DELETE FROM supplier_invoice_lines WHERE supplier_invoice_id=?', (iid,))
            supplier_id = int(request.form['supplier_id'])
            d = request.form.get('invoice_date') or inv['invoice_date']
            due = request.form.get('due_date') or inv['due_date']
            c.execute('UPDATE supplier_invoices SET supplier_id=?,invoice_date=?,due_date=?,status=?,discount=?,vat_rate=?,notes=? WHERE id=?', (
                supplier_id, d, due, request.form.get('status','UNPAID'),
                float(request.form.get('discount') or 0),
                float(request.form.get('vat_rate') or _a.setting('vat') or 15),
                request.form.get('notes',''), iid))

            for item_id, desc, qty, price in zip(
                request.form.getlist('item_id[]'),
                request.form.getlist('description[]'),
                request.form.getlist('qty[]'),
                request.form.getlist('price[]')):
                q = float(qty or 0)
                p = float(price or 0)
                item = int(item_id) if item_id else None
                if not desc.strip() or q <= 0:
                    continue
                c.execute('INSERT INTO supplier_invoice_lines(supplier_invoice_id,item_id,description,qty,unit_price) VALUES(?,?,?,?,?)', (iid,item,desc,q,p))
                if item:
                    c.execute('UPDATE items SET qty=COALESCE(qty,0)+?,active=1 WHERE id=?', (q,item))

            c.commit()
            c.close()
            flash(f'Supplier invoice {inv["number"]} updated successfully.')
            return redirect(url_for('accounts'))
        except Exception as e:
            c.rollback()
            c.close()
            flash(str(e))
            return redirect(url_for('edit_supplier_invoice', iid=iid))

    suppliers = c.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
    items = c.execute("SELECT i.*,ic.name category_name FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id ORDER BY COALESCE(ic.name,'Uncategorised'),i.description").fetchall()
    lines = c.execute('SELECT * FROM supplier_invoice_lines WHERE supplier_invoice_id=? ORDER BY id', (iid,)).fetchall()
    c.close()
    return render_template('supplier_invoice_form.html', suppliers=suppliers, items=items,
                           today=inv['invoice_date'], due=inv['due_date'], editing=True, inv=inv, lines=lines)
