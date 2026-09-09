from flask import render_template, request, redirect, url_for, flash
import app as _a


def dashboard():
    c = _a.db()
    counts = {
        'customers': c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],
        'items': c.execute('SELECT COUNT(*) FROM items WHERE active=1').fetchone()[0],
        # Only invoices that still exist are counted as saved invoices.
        'invoices': c.execute("SELECT COUNT(*) FROM invoices WHERE COALESCE(deleted,0)=0").fetchone()[0],
        'unpaid': c.execute("SELECT COUNT(*) FROM invoices WHERE COALESCE(deleted,0)=0 AND status NOT IN ('PAID','DELETED')").fetchone()[0],
    }
    recent = c.execute('''
        SELECT i.*, c.name customer
        FROM invoices i JOIN customers c ON c.id=i.customer_id
        WHERE COALESCE(i.deleted,0)=0
        ORDER BY i.id DESC LIMIT 8
    ''').fetchall()
    c.close()
    return render_template('dashboard.html', counts=counts, recent=recent)


def delete_invoice(iid):
    c = _a.db()
    try:
        inv = c.execute(
            'SELECT * FROM invoices WHERE id=? AND COALESCE(deleted,0)=0', (iid,)
        ).fetchone()
        if not inv:
            flash('Invoice not found.')
            return redirect(url_for('history'))

        # Restore stock consumed by this invoice before permanently removing it.
        for line in c.execute(
            'SELECT item_id, qty FROM invoice_lines WHERE invoice_id=?', (iid,)
        ).fetchall():
            if line['item_id']:
                c.execute(
                    'UPDATE items SET qty=COALESCE(qty,0)+?, active=1 WHERE id=?',
                    (float(line['qty']), line['item_id'])
                )

        # Payments, sold-item records and invoice lines are transaction records
        # belonging to this invoice and are removed with it.
        if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customer_payments'").fetchone():
            c.execute('DELETE FROM customer_payments WHERE invoice_id=?', (iid,))
        c.execute('DELETE FROM sold_items WHERE invoice_id=?', (iid,))
        c.execute('DELETE FROM invoice_lines WHERE invoice_id=?', (iid,))
        c.execute('DELETE FROM invoices WHERE id=?', (iid,))
        c.commit()
        flash(f"Invoice {inv['number']} permanently deleted. Stock restored.")
        return redirect(url_for('dashboard'))
    except Exception as exc:
        c.rollback()
        flash(f'Could not permanently delete invoice: {exc}')
        return redirect(url_for('dashboard'))
    finally:
        c.close()
