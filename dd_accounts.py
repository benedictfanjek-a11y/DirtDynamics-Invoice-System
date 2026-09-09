# Dirt Dynamics accounting extension. Loaded automatically by Python before Gunicorn imports app.
import sqlite3
from datetime import date, timedelta
from flask import render_template, request, redirect, url_for, flash

try:
    import app as _a
    _app = _a.app

    def _init_accounts():
        c=_a.db()
        c.executescript('''
        CREATE TABLE IF NOT EXISTS customer_payments(
          id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, customer_id INTEGER NOT NULL,
          payment_date TEXT NOT NULL, amount REAL NOT NULL, method TEXT DEFAULT 'Bank Transfer', reference TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE, FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS suppliers(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT, email TEXT, phone TEXT, address TEXT, vat_number TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS supplier_invoices(
          id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, supplier_id INTEGER NOT NULL, invoice_date TEXT NOT NULL, due_date TEXT NOT NULL, status TEXT DEFAULT 'UNPAID', discount REAL DEFAULT 0, vat_rate REAL DEFAULT 15, notes TEXT DEFAULT '', deleted INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(id));
        CREATE TABLE IF NOT EXISTS supplier_invoice_lines(
          id INTEGER PRIMARY KEY, supplier_invoice_id INTEGER NOT NULL, item_id INTEGER, description TEXT NOT NULL, qty REAL NOT NULL, unit_price REAL NOT NULL,
          FOREIGN KEY(supplier_invoice_id) REFERENCES supplier_invoices(id) ON DELETE CASCADE, FOREIGN KEY(item_id) REFERENCES items(id));
        CREATE TABLE IF NOT EXISTS supplier_payments(
          id INTEGER PRIMARY KEY, supplier_invoice_id INTEGER NOT NULL, supplier_id INTEGER NOT NULL, payment_date TEXT NOT NULL, amount REAL NOT NULL, method TEXT DEFAULT 'EFT', reference TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(supplier_invoice_id) REFERENCES supplier_invoices(id) ON DELETE CASCADE, FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE);
        ''')
        ic=[r['name'] for r in c.execute('PRAGMA table_info(items)').fetchall()]
        if 'qty' not in ic:
            c.execute('ALTER TABLE items ADD COLUMN qty REAL NOT NULL DEFAULT 0')
            c.execute('UPDATE items SET qty=1 WHERE active=1 AND COALESCE(qty,0)=0')
        sc=[r['name'] for r in c.execute('PRAGMA table_info(sold_items)').fetchall()]
        if 'qty' not in sc: c.execute('ALTER TABLE sold_items ADD COLUMN qty REAL NOT NULL DEFAULT 1')
        if 'invoice_id' not in sc: c.execute('ALTER TABLE sold_items ADD COLUMN invoice_id INTEGER')
        c.commit(); c.close()
    _init_accounts()

    def _total(c, iid):
        r=c.execute('SELECT discount,vat_rate FROM invoices WHERE id=?',(iid,)).fetchone(); lines=c.execute('SELECT qty,unit_price FROM invoice_lines WHERE invoice_id=?',(iid,)).fetchall()
        sub=sum(float(x['qty'])*float(x['unit_price']) for x in lines); dis=min(max(0,float(r['discount'] or 0)),sub); tax=max(0,sub-dis); return tax+tax*float(r['vat_rate'] or 0)/100
    def _stotal(c, iid):
        r=c.execute('SELECT discount,vat_rate FROM supplier_invoices WHERE id=?',(iid,)).fetchone(); lines=c.execute('SELECT qty,unit_price FROM supplier_invoice_lines WHERE supplier_invoice_id=?',(iid,)).fetchall(); sub=sum(float(x['qty'])*float(x['unit_price']) for x in lines); dis=min(max(0,float(r['discount'] or 0)),sub); tax=max(0,sub-dis); return tax+tax*float(r['vat_rate'] or 0)/100
    def _bounds(m):
        y,mo=map(int,m.split('-')); return f'{y:04d}-{mo:02d}-01', (f'{y+1:04d}-01-01' if mo==12 else f'{y:04d}-{mo+1:02d}-01')
    def _months():
        c=_a.db(); vals=[]
        for q in ['SELECT invoice_date FROM invoices WHERE COALESCE(deleted,0)=0','SELECT invoice_date FROM supplier_invoices WHERE COALESCE(deleted,0)=0','SELECT payment_date FROM customer_payments','SELECT payment_date FROM supplier_payments']:
            vals += [r[0] for r in c.execute(q).fetchall() if r[0]]
        c.close(); out=sorted({x[:7] for x in vals},reverse=True); return out or [date.today().strftime('%Y-%m')]

    def accounts():
        month=request.args.get('month') or date.today().strftime('%Y-%m'); start,end=_bounds(month); c=_a.db()
        def rows(q,typ):
            out=[]
            for r in c.execute(q,(start,end)).fetchall():
                total=_total(c,r['id']) if typ=='sale' else _stotal(c,r['id']); paid=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE invoice_id=?',(r['id'],)).fetchone()[0]) if typ=='sale' else float(c.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_invoice_id=?',(r['id'],)).fetchone()[0]); out.append((r,total,paid,max(0,total-paid)))
            return out
        sales=rows("SELECT i.*,c.name customer FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE COALESCE(i.deleted,0)=0 AND i.invoice_date>=? AND i.invoice_date<? ORDER BY i.invoice_date DESC,i.id DESC",'sale')
        purchases=rows("SELECT si.*,s.name supplier FROM supplier_invoices si JOIN suppliers s ON s.id=si.supplier_id WHERE COALESCE(si.deleted,0)=0 AND si.invoice_date>=? AND si.invoice_date<? ORDER BY si.invoice_date DESC,si.id DESC",'purchase')
        debtors=[]
        for r in c.execute("SELECT i.*,c.name customer FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE COALESCE(i.deleted,0)=0 ORDER BY c.name,i.invoice_date DESC").fetchall():
            t=_total(c,r['id']); p=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE invoice_id=?',(r['id'],)).fetchone()[0]); b=max(0,t-p)
            if b>0: debtors.append((r,t,p,b))
        creditors=[]
        for r in c.execute("SELECT si.*,s.name supplier FROM supplier_invoices si JOIN suppliers s ON s.id=si.supplier_id WHERE COALESCE(si.deleted,0)=0 ORDER BY s.name,si.invoice_date DESC").fetchall():
            t=_stotal(c,r['id']); p=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_invoice_id=?',(r['id'],)).fetchone()[0]); b=max(0,t-p)
            if b>0: creditors.append((r,t,p,b))
        customers=c.execute('SELECT * FROM customers ORDER BY name').fetchall(); suppliers=c.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
        cps=c.execute('SELECT cp.*,c.name customer,i.number invoice_number FROM customer_payments cp JOIN customers c ON c.id=cp.customer_id JOIN invoices i ON i.id=cp.invoice_id WHERE cp.payment_date>=? AND cp.payment_date<? ORDER BY cp.payment_date DESC,cp.id DESC',(start,end)).fetchall()
        sps=c.execute('SELECT sp.*,s.name supplier,si.number invoice_number FROM supplier_payments sp JOIN suppliers s ON s.id=sp.supplier_id JOIN supplier_invoices si ON si.id=sp.supplier_invoice_id WHERE sp.payment_date>=? AND sp.payment_date<? ORDER BY sp.payment_date DESC,sp.id DESC',(start,end)).fetchall()
        totals={'sales':sum(x[1] for x in sales),'purchases':sum(x[1] for x in purchases),'debtors':sum(x[3] for x in debtors),'creditors':sum(x[3] for x in creditors)}; c.close()
        return render_template('accounts.html',month=month,months=_months(),today=str(date.today()),sales=sales,debtors=debtors,purchases=purchases,creditors=creditors,customers=customers,suppliers=suppliers,customer_payments=cps,supplier_payments=sps,totals=totals)

    def add_cp():
        c=_a.db(); iid=int(request.form['invoice_id']); inv=c.execute('SELECT * FROM invoices WHERE id=? AND deleted=0',(iid,)).fetchone(); amount=float(request.form['amount']); total=_total(c,iid); paid=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE invoice_id=?',(iid,)).fetchone()[0])
        if not inv or amount<=0 or amount>total-paid+0.01: c.close(); flash('Invalid payment amount or invoice.'); return redirect(url_for('accounts',month=request.form.get('month')))
        c.execute('INSERT INTO customer_payments(invoice_id,customer_id,payment_date,amount,method,reference,notes) VALUES(?,?,?,?,?,?,?)',(iid,inv['customer_id'],request.form.get('payment_date') or str(date.today()),amount,request.form.get('method','Bank Transfer'),request.form.get('reference',''),request.form.get('notes',''))); new=paid+amount; c.execute('UPDATE invoices SET status=? WHERE id=?',('PAID' if new>=total-0.01 else ('PARTIAL' if new>0 else 'UNPAID'),iid)); c.commit(); c.close(); flash('Customer payment recorded.'); return redirect(url_for('accounts',month=request.form.get('month')))
    def add_sp():
        c=_a.db(); iid=int(request.form['supplier_invoice_id']); inv=c.execute('SELECT * FROM supplier_invoices WHERE id=? AND deleted=0',(iid,)).fetchone(); amount=float(request.form['amount']); total=_stotal(c,iid); paid=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_invoice_id=?',(iid,)).fetchone()[0])
        if not inv or amount<=0 or amount>total-paid+0.01: c.close(); flash('Invalid supplier payment.'); return redirect(url_for('accounts',month=request.form.get('month')))
        c.execute('INSERT INTO supplier_payments(supplier_invoice_id,supplier_id,payment_date,amount,method,reference,notes) VALUES(?,?,?,?,?,?,?)',(iid,inv['supplier_id'],request.form.get('payment_date') or str(date.today()),amount,request.form.get('method','EFT'),request.form.get('reference',''),request.form.get('notes',''))); new=paid+amount; c.execute('UPDATE supplier_invoices SET status=? WHERE id=?',('PAID' if new>=total-0.01 else ('PARTIAL' if new>0 else 'UNPAID'),iid)); c.commit(); c.close(); flash('Supplier payment recorded.'); return redirect(url_for('accounts',month=request.form.get('month')))
    def add_supplier():
        c=_a.db(); c.execute('INSERT INTO suppliers(name,company,email,phone,address,vat_number,notes) VALUES(?,?,?,?,?,?,?)',tuple(request.form.get(k,'') for k in ['name','company','email','phone','address','vat_number','notes'])); c.commit(); c.close(); flash('Supplier added.'); return redirect(url_for('accounts'))
    def new_purchase():
        c=_a.db(); suppliers=c.execute('SELECT * FROM suppliers ORDER BY name').fetchall(); items=c.execute("SELECT i.*,ic.name category_name FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id ORDER BY COALESCE(ic.name,'Uncategorised'),i.description").fetchall()
        if request.method=='POST':
            try:
                num=request.form.get('number') or 'SUP-'+date.today().strftime('%Y%m%d')+'-'+str(c.execute('SELECT COUNT(*) FROM supplier_invoices').fetchone()[0]+1); sid=int(request.form['supplier_id']); d=request.form.get('invoice_date') or str(date.today()); due=request.form.get('due_date') or d; c.execute('INSERT INTO supplier_invoices(number,supplier_id,invoice_date,due_date,status,discount,vat_rate,notes) VALUES(?,?,?,?,?,?,?,?)',(num,sid,d,due,request.form.get('status','UNPAID'),float(request.form.get('discount') or 0),float(request.form.get('vat_rate') or _a.setting('vat') or 15),request.form.get('notes',''))); iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                for item_id,desc,qty,price in zip(request.form.getlist('item_id[]'),request.form.getlist('description[]'),request.form.getlist('qty[]'),request.form.getlist('price[]')):
                    q=float(qty or 0); p=float(price or 0); item=int(item_id) if item_id else None
                    if not desc.strip() or q<=0: continue
                    c.execute('INSERT INTO supplier_invoice_lines(supplier_invoice_id,item_id,description,qty,unit_price) VALUES(?,?,?,?,?)',(iid,item,desc,q,p));
                    if item: c.execute('UPDATE items SET qty=COALESCE(qty,0)+?,active=1 WHERE id=?',(q,item))
                c.commit(); c.close(); flash('Purchase recorded and inventory increased.'); return redirect(url_for('accounts',month=d[:7]))
            except Exception as e: c.rollback(); c.close(); flash(str(e)); return redirect(url_for('new_supplier_invoice'))
        c.close(); return render_template('supplier_invoice_form.html',suppliers=suppliers,items=items,today=str(date.today()),due=str(date.today()),editing=False,inv=None,lines=[])
    def delete_sp_invoice(iid):
        c=_a.db(); inv=c.execute('SELECT * FROM supplier_invoices WHERE id=? AND deleted=0',(iid,)).fetchone()
        if inv:
            if float(c.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_invoice_id=?',(iid,)).fetchone()[0])>0: c.close(); flash('Delete supplier payments first.'); return redirect(url_for('accounts'))
            for l in c.execute('SELECT item_id,qty FROM supplier_invoice_lines WHERE supplier_invoice_id=?',(iid,)).fetchall():
                if l['item_id']: c.execute('UPDATE items SET qty=max(0,COALESCE(qty,0)-?),active=CASE WHEN qty-?>0 THEN 1 ELSE 0 END WHERE id=?',(float(l['qty']),float(l['qty']),l['item_id']))
            c.execute('UPDATE supplier_invoices SET deleted=1 WHERE id=?',(iid,)); c.commit()
        c.close(); flash('Supplier invoice deleted and stock reversed.'); return redirect(url_for('accounts'))
    def delete_cp(pid):
        c=_a.db(); p=c.execute('SELECT invoice_id FROM customer_payments WHERE id=?',(pid,)).fetchone()
        if p: c.execute('DELETE FROM customer_payments WHERE id=?',(pid,)); t=_total(c,p['invoice_id']); paid=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE invoice_id=?',(p['invoice_id'],)).fetchone()[0]); c.execute('UPDATE invoices SET status=? WHERE id=?',('PAID' if paid>=t-0.01 else ('PARTIAL' if paid>0 else 'UNPAID'),p['invoice_id'])); c.commit()
        c.close(); flash('Customer payment deleted.'); return redirect(url_for('accounts'))
    def delete_sp(pid):
        c=_a.db(); p=c.execute('SELECT supplier_invoice_id FROM supplier_payments WHERE id=?',(pid,)).fetchone()
        if p: c.execute('DELETE FROM supplier_payments WHERE id=?',(pid,)); t=_stotal(c,p['supplier_invoice_id']); paid=float(c.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier_invoice_id=?',(p['supplier_invoice_id'],)).fetchone()[0]); c.execute('UPDATE supplier_invoices SET status=? WHERE id=?',('PAID' if paid>=t-0.01 else ('PARTIAL' if paid>0 else 'UNPAID'),p['supplier_invoice_id'])); c.commit()
        c.close(); flash('Supplier payment deleted.'); return redirect(url_for('accounts'))
    def statement():
        typ=request.args.get('type','customer'); eid=int(request.args.get('id','0')); month=request.args.get('month') or date.today().strftime('%Y-%m'); start,end=_bounds(month); c=_a.db(); rows=[]
        if typ=='customer':
            ent=c.execute('SELECT * FROM customers WHERE id=?',(eid,)).fetchone(); title=f"Customer Statement — {ent['name']}" if ent else 'Customer Statement'; opening=sum(_total(c,r['id']) for r in c.execute('SELECT id FROM invoices WHERE customer_id=? AND COALESCE(deleted,0)=0 AND invoice_date<?',(eid,start)).fetchall())-sum(float(r[0]) for r in c.execute('SELECT amount FROM customer_payments WHERE customer_id=? AND payment_date<?',(eid,start)).fetchall())
            for r in c.execute('SELECT * FROM invoices WHERE customer_id=? AND COALESCE(deleted,0)=0 AND invoice_date>=? AND invoice_date<? ORDER BY invoice_date,id',(eid,start,end)).fetchall(): rows.append((r['invoice_date'],r['number'],'Invoice / Sale',_total(c,r['id']),0))
            for r in c.execute('SELECT * FROM customer_payments WHERE customer_id=? AND payment_date>=? AND payment_date<? ORDER BY payment_date,id',(eid,start,end)).fetchall(): rows.append((r['payment_date'],r['reference'] or 'Payment','Customer payment',0,float(r['amount'])))
        else:
            ent=c.execute('SELECT * FROM suppliers WHERE id=?',(eid,)).fetchone(); title=f"Supplier Statement — {ent['name']}" if ent else 'Supplier Statement'; opening=sum(_stotal(c,r['id']) for r in c.execute('SELECT id FROM supplier_invoices WHERE supplier_id=? AND COALESCE(deleted,0)=0 AND invoice_date<?',(eid,start)).fetchall())-sum(float(r[0]) for r in c.execute('SELECT amount FROM supplier_payments WHERE supplier_id=? AND payment_date<?',(eid,start)).fetchall())
            for r in c.execute('SELECT * FROM supplier_invoices WHERE supplier_id=? AND COALESCE(deleted,0)=0 AND invoice_date>=? AND invoice_date<? ORDER BY invoice_date,id',(eid,start,end)).fetchall(): rows.append((r['invoice_date'],r['number'],'Supplier invoice / Purchase',_stotal(c,r['id']),0))
            for r in c.execute('SELECT * FROM supplier_payments WHERE supplier_id=? AND payment_date>=? AND payment_date<? ORDER BY payment_date,id',(eid,start,end)).fetchall(): rows.append((r['payment_date'],r['reference'] or 'Payment','Supplier payment',0,float(r['amount'])))
        rows.sort(); bal=opening; out=[]
        for d,ref,desc,ch,pay in rows: bal+=ch-pay; out.append({'date':d,'ref':ref,'description':desc,'charge':ch,'payment':pay,'balance':bal})
        c.close(); return render_template('account_statement.html',company=_a.company(),title=title,month=month,opening=opening,charges=sum(x['charge'] for x in out),payments=sum(x['payment'] for x in out),closing=bal,rows=out)

    def new_invoice_v2():
        c=_a.db(); customers=c.execute('SELECT * FROM customers ORDER BY name').fetchall(); items=c.execute("SELECT i.*,ic.name category_name FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id WHERE i.active=1 AND COALESCE(i.qty,0)>0 ORDER BY COALESCE(ic.name,'Uncategorised'),i.description").fetchall()
        if request.method=='POST':
            try:
                invdate=request.form.get('invoice_date') or str(date.today()); due=request.form.get('due_date') or str(date.today()+timedelta(days=int(_a.setting('terms') or 14))); num=_a.next_invoice(); c.execute('INSERT INTO invoices(number,customer_id,invoice_date,due_date,status,discount,vat_rate,notes) VALUES(?,?,?,?,?,?,?,?)',(num,int(request.form['customer_id']),invdate,due,request.form.get('status','UNPAID'),float(request.form.get('discount') or 0),float(request.form.get('vat_rate') or _a.setting('vat') or 15),request.form.get('notes',''))); iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                for item_id,desc,qty,price in zip(request.form.getlist('item_id[]'),request.form.getlist('description[]'),request.form.getlist('qty[]'),request.form.getlist('price[]')):
                    q=float(qty or 0); p=float(price or 0); item=int(item_id) if item_id else None
                    if not desc.strip() or q<=0: continue
                    if item:
                        stock=c.execute('SELECT qty FROM items WHERE id=? AND active=1',(item,)).fetchone(); avail=float(stock['qty']) if stock else 0
                        if q>avail: raise ValueError(f'Not enough stock for {desc}. Available: {avail:g}')
                        c.execute('UPDATE items SET qty=qty-? WHERE id=?',(q,item)); c.execute('UPDATE items SET active=0 WHERE id=? AND qty<=0',(item,))
                    c.execute('INSERT INTO invoice_lines(invoice_id,item_id,description,qty,unit_price) VALUES(?,?,?,?,?)',(iid,item,desc,q,p))
                    if item:
                        vr=float(request.form.get('vat_rate') or _a.setting('vat') or 15); lt=q*p; va=lt*vr/100; c.execute('INSERT INTO sold_items(invoice_id,item_id,description,sold_date,selling_price,vat_rate,vat_amount,total,cost_price,profit,qty) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,item,desc,invdate,p,vr,va,lt+va,0,p*q,q))
                c.commit(); c.close(); return redirect(url_for('view_invoice',iid=iid))
            except Exception as e: c.rollback(); c.close(); flash(str(e)); return redirect(url_for('new_invoice'))
        c.close(); return render_template('invoice_form.html',customers=customers,items=items,today=str(date.today()),due=str(date.today()+timedelta(days=int(_a.setting('terms') or 14))),editing=False,inv=None,lines=[])

    def edit_invoice(iid):
        c=_a.db(); inv=c.execute('SELECT * FROM invoices WHERE id=? AND COALESCE(deleted,0)=0',(iid,)).fetchone()
        if not inv: c.close(); return 'Not found',404
        if request.method=='POST':
            try:
                for l in c.execute('SELECT item_id,qty FROM invoice_lines WHERE invoice_id=?',(iid,)).fetchall():
                    if l['item_id']: c.execute('UPDATE items SET qty=COALESCE(qty,0)+?,active=1 WHERE id=?',(float(l['qty']),l['item_id']))
                c.execute('DELETE FROM sold_items WHERE invoice_id=?',(iid,)); c.execute('DELETE FROM invoice_lines WHERE invoice_id=?',(iid,)); d=request.form.get('invoice_date') or inv['invoice_date']; due=request.form.get('due_date') or inv['due_date']; c.execute('UPDATE invoices SET customer_id=?,invoice_date=?,due_date=?,status=?,discount=?,vat_rate=?,notes=? WHERE id=?',(int(request.form['customer_id']),d,due,request.form.get('status','UNPAID'),float(request.form.get('discount') or 0),float(request.form.get('vat_rate') or _a.setting('vat') or 15),request.form.get('notes',''),iid))
                for item_id,desc,qty,price in zip(request.form.getlist('item_id[]'),request.form.getlist('description[]'),request.form.getlist('qty[]'),request.form.getlist('price[]')):
                    q=float(qty or 0); pr=float(price or 0); item=int(item_id) if item_id else None
                    if not desc.strip() or q<=0: continue
                    if item:
                        st=c.execute('SELECT qty FROM items WHERE id=?',(item,)).fetchone(); av=float(st['qty']) if st else 0
                        if q>av: raise ValueError(f'Not enough stock for {desc}. Available: {av:g}')
                        c.execute('UPDATE items SET qty=qty-? WHERE id=?',(q,item)); c.execute('UPDATE items SET active=0 WHERE id=? AND qty<=0',(item,))
                    c.execute('INSERT INTO invoice_lines(invoice_id,item_id,description,qty,unit_price) VALUES(?,?,?,?,?)',(iid,item,desc,q,pr))
                    if item:
                        vr=float(request.form.get('vat_rate') or _a.setting('vat') or 15); lt=q*pr; va=lt*vr/100; c.execute('INSERT INTO sold_items(invoice_id,item_id,description,sold_date,selling_price,vat_rate,vat_amount,total,cost_price,profit,qty) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,item,desc,d,pr,vr,va,lt+va,0,pr*q,q))
                c.commit(); c.close(); flash(f'Invoice {inv["number"]} updated successfully.'); return redirect(url_for('view_invoice',iid=iid))
            except Exception as e: c.rollback(); c.close(); flash(str(e)); return redirect(url_for('edit_invoice',iid=iid))
        customers=c.execute('SELECT * FROM customers ORDER BY name').fetchall(); items=c.execute("SELECT i.*,ic.name category_name FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id WHERE i.active=1 OR i.id IN (SELECT item_id FROM invoice_lines WHERE invoice_id=? AND item_id IS NOT NULL) ORDER BY COALESCE(ic.name,'Uncategorised'),i.description",(iid,)).fetchall(); lines=c.execute('SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id',(iid,)).fetchall(); c.close(); return render_template('invoice_form.html',customers=customers,items=items,today=inv['invoice_date'],due=inv['due_date'],editing=True,inv=inv,lines=lines)

    def delete_invoice(iid):
        c=_a.db(); inv=c.execute('SELECT * FROM invoices WHERE id=? AND COALESCE(deleted,0)=0',(iid,)).fetchone()
        if not inv: c.close(); flash('Invoice not found.'); return redirect(url_for('history'))
        if float(c.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE invoice_id=?',(iid,)).fetchone()[0])>0: c.close(); flash('Delete customer payments first.'); return redirect(url_for('view_invoice',iid=iid))
        for l in c.execute('SELECT item_id,qty FROM invoice_lines WHERE invoice_id=?',(iid,)).fetchall():
            if l['item_id']: c.execute('UPDATE items SET qty=COALESCE(qty,0)+?,active=1 WHERE id=?',(float(l['qty']),l['item_id']))
        c.execute('DELETE FROM sold_items WHERE invoice_id=?',(iid,)); c.execute('UPDATE invoices SET deleted=1 WHERE id=?',(iid,)); c.commit(); c.close(); flash('Invoice deleted and stock restored.'); return redirect(url_for('history'))

    _app.view_functions['new_invoice']=new_invoice_v2
    _app.view_functions['delete_invoice']=delete_invoice
    _app.view_functions['items']=inventory_view
    _app.view_functions['mark_item_sold']=sold_v2
    _app.add_url_rule('/invoice/<int:iid>/edit','edit_invoice',edit_invoice,methods=['GET','POST'])
    _app.add_url_rule('/item/<int:iid>/edit','edit_item_v2',edit_item,methods=['GET','POST'])
    _app.add_url_rule('/accounts','accounts',accounts)
    _app.add_url_rule('/accounts/customer','add_customer_payment',add_cp,methods=['POST'])
    _app.add_url_rule('/accounts/supplier','add_supplier_payment',add_sp,methods=['POST'])
    _app.add_url_rule('/accounts/supplier/add','add_supplier',add_supplier,methods=['POST'])
    _app.add_url_rule('/accounts/purchase/new','new_supplier_invoice',new_purchase,methods=['GET','POST'])
    _app.add_url_rule('/accounts/purchase/<int:iid>/delete','delete_supplier_invoice',delete_sp_invoice,methods=['POST'])
    _app.add_url_rule('/accounts/customer-payment/<int:pid>/delete','delete_customer_payment',delete_cp,methods=['POST'])
    _app.add_url_rule('/accounts/supplier-payment/<int:pid>/delete','delete_supplier_payment',delete_sp,methods=['POST'])
    _app.add_url_rule('/accounts/statement','account_statement',statement)

    @_app.after_request
    def _dd_nav(response):
        if response.content_type and 'text/html' in response.content_type and response.status_code==200:
            try:
                body=response.get_data(as_text=True)
                if 'Parts &amp; Services</a>' in body and '>Accounts</a>' not in body:
                    body=body.replace('Parts &amp; Services</a>','Inventory</a><a href="/accounts"><span class="side-icon">▤</span>Accounts</a>')
                response.set_data(body)
            except Exception: pass
        return response
except Exception:
    pass
