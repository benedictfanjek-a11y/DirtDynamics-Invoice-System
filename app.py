import os, sqlite3, secrets, hashlib, re, zipfile, tempfile, shutil, json
from datetime import date, timedelta, datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
from io import BytesIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Database location: use Render Persistent Disk when available, otherwise local project folder.
PERSISTENT_DATA_DIR = os.environ.get("DirtDynamics_DATA_DIR", "/var/data")
if os.path.isdir(PERSISTENT_DATA_DIR) and os.access(PERSISTENT_DATA_DIR, os.W_OK):
    DB_PATH = os.path.join(PERSISTENT_DATA_DIR, "dirt_dynamics.db")
    # On first deployment with a persistent disk, preserve an existing local database.
    _legacy_db = os.path.join(BASE_DIR, "dirt_dynamics.db")
    if not os.path.exists(DB_PATH) and os.path.exists(_legacy_db):
        shutil.copy2(_legacy_db, DB_PATH)
else:
    DB_PATH = os.path.join(BASE_DIR, "dirt_dynamics.db")
app = Flask(__name__)
app.secret_key = os.environ.get("DD_SECRET_KEY", secrets.token_hex(32))

COMPANY_DEFAULTS = {
    "name": "DIRT DYNAMICS (PTY) LTD",
    "address": "Unit 5, 123 Mosaic Street, Silvertondale, Pretoria",
    "email": "benny@dirtdynamics.co.za",
    "phone": "",
    "vat": "15",
    "terms": "14",
    "bank_name": "Capitec Business",
    "account_type": "Capitec Business Account",
    "account_name": "DIRT DYNAMICS (PTY)LTD",
    "account_number": "1055685758",
    "branch_name": "Relationship Suite",
    "branch_code": "450105",
    "tagline": "Built by Strength • Driven by Excellence"
}

def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, created_at TEXT, role TEXT DEFAULT 'admin');
    CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT, email TEXT, phone TEXT,
        address TEXT, vat_number TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS item_categories(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY, code TEXT, description TEXT NOT NULL, price REAL NOT NULL DEFAULT 0,
        unit TEXT DEFAULT 'each', active INTEGER DEFAULT 1, category_id INTEGER,
        FOREIGN KEY(category_id) REFERENCES item_categories(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, customer_id INTEGER NOT NULL,
        invoice_date TEXT NOT NULL, due_date TEXT NOT NULL, status TEXT DEFAULT 'UNPAID',
        discount REAL DEFAULT 0, vat_rate REAL DEFAULT 15, notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS invoice_lines(
        id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, item_id INTEGER,
        description TEXT NOT NULL, qty REAL NOT NULL, unit_price REAL NOT NULL,
        FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
        FOREIGN KEY(item_id) REFERENCES items(id)
    );
        CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        full_name TEXT NOT NULL,
        employee_number TEXT UNIQUE,
        face_image TEXT,
        consent_given INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS employee_rates(
        id INTEGER PRIMARY KEY,
        employee_id INTEGER UNIQUE NOT NULL,
        hourly_rate REAL NOT NULL DEFAULT 0,
        day_rate REAL NOT NULL DEFAULT 0,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS face_samples(
        id INTEGER PRIMARY KEY,
        employee_id INTEGER NOT NULL,
        image TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY,
        employee_id INTEGER NOT NULL,
        clock_in TEXT,
        clock_out TEXT,
        clock_in_photo TEXT,
        clock_out_photo TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id)
    );
    CREATE TABLE IF NOT EXISTS sold_items(
        id INTEGER PRIMARY KEY,
        item_id INTEGER,
        description TEXT NOT NULL,
        sold_date TEXT NOT NULL,
        selling_price REAL NOT NULL DEFAULT 0,
        vat_rate REAL NOT NULL DEFAULT 15,
        vat_amount REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0,
        cost_price REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        FOREIGN KEY(item_id) REFERENCES items(id)
    );
    """)
    # Migration for existing installations: keep deleted invoices in the database,
    # but hide them from normal invoice history.
    user_cols=[r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "role" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin'")
    c.execute("UPDATE users SET role='admin' WHERE username='benedictfanjek@gmail.com'")
    cols=[r["name"] for r in c.execute("PRAGMA table_info(invoices)").fetchall()]
    if "deleted" not in cols:
        c.execute("ALTER TABLE invoices ADD COLUMN deleted INTEGER DEFAULT 0")
    item_cols=[r["name"] for r in c.execute("PRAGMA table_info(items)").fetchall()]
    if "category_id" not in item_cols:
        c.execute("ALTER TABLE items ADD COLUMN category_id INTEGER")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_item_categories_name ON item_categories(name)")

    employee_cols=[r["name"] for r in c.execute("PRAGMA table_info(employees)").fetchall()]
    if "email" not in employee_cols:
        c.execute("ALTER TABLE employees ADD COLUMN email TEXT DEFAULT ''")
    c.execute("""CREATE TABLE IF NOT EXISTS employee_attendance_days(
        id INTEGER PRIMARY KEY,
        employee_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        employee_marked INTEGER DEFAULT 0,
        final_worked INTEGER DEFAULT 0,
        employee_marked_at TEXT,
        admin_updated_at TEXT,
        admin_updated_by INTEGER,
        UNIQUE(employee_id, work_date),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(admin_updated_by) REFERENCES users(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS employee_monthly_rates(
        id INTEGER PRIMARY KEY,
        employee_id INTEGER NOT NULL,
        month TEXT NOT NULL,
        day_rate REAL NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER,
        UNIQUE(employee_id, month),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(updated_by) REFERENCES users(id)
    )""")

    sold_cols=[r["name"] for r in c.execute("PRAGMA table_info(sold_items)").fetchall()]
    if "cost_price" not in sold_cols:
        c.execute("ALTER TABLE sold_items ADD COLUMN cost_price REAL DEFAULT 0")
    if "profit" not in sold_cols:
        c.execute("ALTER TABLE sold_items ADD COLUMN profit REAL DEFAULT 0")
    c.execute("UPDATE invoices SET deleted=0 WHERE deleted IS NULL")
    for k,v in COMPANY_DEFAULTS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.execute("INSERT INTO users(username,password_hash,created_at,role) VALUES(?,?,?,?)",
                  ("benedictfanjek@gmail.com", generate_password_hash("Titans_2017"), str(date.today()), "admin"))
    c.commit(); c.close()

def setting(k):
    c=db(); r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone(); c.close()
    return r["value"] if r else ""

def company():
    c=db(); rows=c.execute("SELECT key,value FROM settings").fetchall(); c.close()
    return {r["key"]:r["value"] for r in rows}

def next_invoice():
    # Never reuse an invoice number, including after an invoice is deleted.
    c=db()
    rows=c.execute("SELECT number FROM invoices").fetchall()
    c.close()
    highest=0
    for r in rows:
        m=re.search(r"(\d+)$", r["number"] or "")
        if m:
            highest=max(highest,int(m.group(1)))
    return f"INV-{highest+1:05d}"

def totals(inv_id):
    c=db()
    rows=c.execute("SELECT qty,unit_price FROM invoice_lines WHERE invoice_id=?",(inv_id,)).fetchall()
    inv=c.execute("SELECT discount,vat_rate FROM invoices WHERE id=?",(inv_id,)).fetchone()
    subtotal=sum(float(x["qty"])*float(x["unit_price"]) for x in rows)
    discount=max(0,float(inv["discount"] or 0))
    taxable=max(0,subtotal-discount)
    vat=taxable*float(inv["vat_rate"] or 0)/100
    return subtotal,discount,vat,taxable+vat

@app.template_filter("datetime_day")
def datetime_day(value):
    try: return date.fromisoformat(value).strftime("%A")
    except Exception: return ""

@app.before_request
def startup():
    init_db()

@app.context_processor
def inject():
    c=db(); current_user=None
    if session.get("user_id"):
        current_user=c.execute("SELECT id, username, role FROM users WHERE id=?",(session["user_id"],)).fetchone()
    c.close()
    return {"company": company(), "current_user": current_user}

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        c=db(); u=c.execute("SELECT * FROM users WHERE username=?",(request.form["username"],)).fetchone(); c.close()
        if u and check_password_hash(u["password_hash"], request.form["password"]):
            session["uid"]=u["id"]
            session["user_id"]=u["id"]
            session["employee_view"]=(u["role"] == "employee")
            if u["role"] == "employee":
                return redirect(url_for("employee_portal"))
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.before_request
def auth():
    if request.endpoint not in ("login","employee_register","static") and "uid" not in session:
        return redirect(url_for("login"))

@app.route("/")
def dashboard():
    c=db()
    counts={
        "customers":c.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "items":c.execute("SELECT COUNT(*) FROM items WHERE active=1").fetchone()[0],
        "invoices":c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0],
        "unpaid":c.execute("SELECT COUNT(*) FROM invoices WHERE status!='PAID'").fetchone()[0],
    }
    recent=c.execute("""SELECT i.*,c.name customer FROM invoices i JOIN customers c ON c.id=i.customer_id
                        ORDER BY i.id DESC LIMIT 8""").fetchall(); c.close()
    return render_template("dashboard.html",counts=counts,recent=recent)

@app.route("/customers", methods=["GET","POST"])
def customers():
    c=db()
    if request.method=="POST":
        c.execute("""INSERT INTO customers(name,company,email,phone,address,vat_number,notes)
                     VALUES(?,?,?,?,?,?,?)""",
                  tuple(request.form.get(x,"") for x in ["name","company","email","phone","address","vat_number","notes"]))
        c.commit()
        flash("Customer added successfully.")
    rows=c.execute("SELECT * FROM customers ORDER BY name").fetchall(); c.close()
    return render_template("customers.html",customers=rows)

@app.route("/customers/delete/<int:cid>", methods=["POST"])
def delete_customer(cid):
    if not admin_only():
        return redirect(url_for("employee_portal"))
    c=db()
    customer=c.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not customer:
        c.close()
        flash("Customer not found.")
        return redirect(url_for("customers"))
    # Only active invoices should prevent customer deletion.
    # Invoices that were deleted from Invoice History are already marked
    # deleted=1; purge those hidden records (and their lines) so the
    # customer can be removed cleanly without breaking foreign keys.
    active_invoice_count=c.execute(
        "SELECT COUNT(*) FROM invoices WHERE customer_id=? AND COALESCE(deleted,0)=0",
        (cid,)
    ).fetchone()[0]
    if active_invoice_count:
        c.close()
        flash("Customer cannot be deleted because they still have active invoices. Delete those invoices from Invoice History first.")
        return redirect(url_for("customers"))

    deleted_ids=[r[0] for r in c.execute(
        "SELECT id FROM invoices WHERE customer_id=? AND COALESCE(deleted,0)=1",
        (cid,)
    ).fetchall()]
    if deleted_ids:
        placeholders=",".join("?" for _ in deleted_ids)
        c.execute(f"DELETE FROM invoice_lines WHERE invoice_id IN ({placeholders})", deleted_ids)
        c.execute(f"DELETE FROM invoices WHERE id IN ({placeholders})", deleted_ids)

    c.execute("DELETE FROM customers WHERE id=?", (cid,))
    c.commit(); c.close()
    flash("Customer deleted successfully.")
    return redirect(url_for("customers"))

@app.route("/items", methods=["GET","POST"])
def items():
    c=db()
    selected = request.args.get("category", "all")

    if request.method=="POST":
        action=request.form.get("action", "add_item")
        if action=="add_category":
            name=request.form.get("category_name", "").strip()
            if not name:
                flash("Enter a category name.")
            else:
                try:
                    c.execute("INSERT INTO item_categories(name) VALUES(?)", (name,))
                    c.commit()
                    flash(f"Category '{name}' added.")
                    new_cat=c.execute("SELECT id FROM item_categories WHERE name=?",(name,)).fetchone()
                    c.close()
                    return redirect(url_for("items", category=new_cat["id"]))
                except sqlite3.IntegrityError:
                    c.rollback()
                    flash("That category already exists.")
        else:
            category_id=request.form.get("category_id") or None
            description=request.form.get("description", "").strip()
            if not description:
                flash("Part description is required.")
            else:
                c.execute("INSERT INTO items(code,description,price,unit,category_id) VALUES(?,?,?,?,?)",
                          (request.form.get("code",""),description,float(request.form.get("price") or 0),
                           request.form.get("unit","each"),int(category_id) if category_id else None))
                c.commit()
                flash(f"{description} added to inventory.")
                selected = category_id or "all"

    categories=c.execute("""
        SELECT ic.id, ic.name, COUNT(i.id) AS item_count
        FROM item_categories ic
        LEFT JOIN items i ON i.category_id=ic.id AND i.active=1
        WHERE ic.active=1
        GROUP BY ic.id, ic.name
        ORDER BY ic.name
    """).fetchall()

    if selected=="all":
        rows=c.execute("""SELECT i.*, ic.name AS category_name
                         FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id
                         WHERE i.active=1 ORDER BY COALESCE(ic.name,'Uncategorised'), i.description""").fetchall()
        selected_category=None
    else:
        try:
            cat_id=int(selected)
        except ValueError:
            cat_id=-1
        selected_category=c.execute("SELECT * FROM item_categories WHERE id=? AND active=1",(cat_id,)).fetchone()
        if selected_category:
            rows=c.execute("""SELECT i.*, ic.name AS category_name
                             FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id
                             WHERE i.active=1 AND i.category_id=? ORDER BY i.description""",(cat_id,)).fetchall()
        else:
            selected="all"
            rows=c.execute("""SELECT i.*, ic.name AS category_name
                             FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id
                             WHERE i.active=1 ORDER BY COALESCE(ic.name,'Uncategorised'), i.description""").fetchall()

    c.close()
    return render_template("items.html", items=rows, categories=categories, selected_category=selected_category, selected=selected)

@app.route("/items/category/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id):
    if not admin_only():
        return redirect(url_for("employee_portal"))
    c = db()
    category = c.execute("SELECT id, name FROM item_categories WHERE id=? AND active=1", (category_id,)).fetchone()
    if not category:
        c.close()
        flash("Category not found.")
        return redirect(url_for("items"))

    # Preserve the parts themselves. Removing a category simply leaves its
    # parts uncategorised, so no inventory, invoice or sold history is lost.
    c.execute("UPDATE items SET category_id=NULL WHERE category_id=?", (category_id,))
    c.execute("DELETE FROM item_categories WHERE id=?", (category_id,))
    c.commit()
    c.close()
    flash(f"Category '{category['name']}' deleted. Its parts were kept in All Inventory.")
    return redirect(url_for("items"))

@app.route("/item/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    if not admin_only():
        return redirect(url_for("employee_portal"))
    c = db()
    try:
        item = c.execute("SELECT id, description, active FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            flash("Part not found.")
            return redirect(url_for("items"))

        # Preserve invoice and sold history by removing only the foreign-key link.
        c.execute("UPDATE invoice_lines SET item_id=NULL WHERE item_id=?", (item_id,))
        c.execute("UPDATE sold_items SET item_id=NULL WHERE item_id=?", (item_id,))
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
        c.commit()
        flash(f"Part '{item['description']}' deleted successfully.")
    except Exception as exc:
        c.rollback()
        flash(f"Could not delete part: {exc}")
    finally:
        c.close()
    return redirect(url_for("items", category=request.args.get("category", "all")))

@app.route("/item/<int:item_id>/category", methods=["POST"])
def change_item_category(item_id):
    if not admin_only():
        return redirect(url_for("employee_portal"))
    c = db()
    try:
        item = c.execute("SELECT id, description, active FROM items WHERE id=?", (item_id,)).fetchone()
        if not item or not item["active"]:
            flash("Part not found or is no longer active.")
            return redirect(url_for("items", category="all"))
        category_id = request.form.get("category_id")
        try:
            category_id = int(category_id) if category_id else None
        except (TypeError, ValueError):
            category_id = None
        if category_id is None:
            flash("Please select a category.")
            return redirect(url_for("items", category="all"))
        category = c.execute("SELECT id, name FROM item_categories WHERE id=? AND active=1", (category_id,)).fetchone()
        if not category:
            flash("Category not found.")
            return redirect(url_for("items", category="all"))
        c.execute("UPDATE items SET category_id=? WHERE id=?", (category_id, item_id))
        c.commit()
        flash(f"{item['description']} moved to '{category['name']}'.")
    except Exception as exc:
        c.rollback()
        flash(f"Could not change category: {exc}")
    finally:
        c.close()
    return redirect(url_for("items", category=request.args.get("category", "all")))

@app.route("/items/report")
def items_report():
    selected = request.args.get("category", "all")
    c = db()
    selected_category = None
    if selected != "all":
        try:
            cat_id = int(selected)
        except ValueError:
            cat_id = -1
        selected_category = c.execute("SELECT * FROM item_categories WHERE id=? AND active=1", (cat_id,)).fetchone()
        if not selected_category:
            selected = "all"
    if selected == "all":
        rows = c.execute("""SELECT i.*, ic.name AS category_name
                           FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id
                           WHERE i.active=1
                           ORDER BY COALESCE(ic.name,'Uncategorised'), i.code, i.description""").fetchall()
        report_title = "ALL INVENTORY"
        report_subtitle = "COMPLETE ACTIVE PARTS & SERVICES INVENTORY"
    else:
        rows = c.execute("""SELECT i.*, ic.name AS category_name
                           FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id
                           WHERE i.active=1 AND i.category_id=?
                           ORDER BY i.code, i.description""", (selected_category["id"],)).fetchall()
        report_title = f"{selected_category['name'].upper()} INVENTORY"
        report_subtitle = f"ACTIVE INVENTORY — {selected_category['name'].upper()}"
    count = len(rows)
    c.close()
    return render_template("inventory_report.html", items=rows, selected=selected, selected_category=selected_category, report_title=report_title, report_subtitle=report_subtitle, count=count, current_date=date.today().strftime("%d/%m/%Y"))

@app.route("/invoice/new", methods=["GET","POST"])
def new_invoice():
    c=db()
    customers=c.execute("SELECT * FROM customers ORDER BY name").fetchall()
    items=c.execute("""SELECT i.*, ic.name AS category_name
                     FROM items i LEFT JOIN item_categories ic ON ic.id=i.category_id
                     WHERE i.active=1 ORDER BY COALESCE(ic.name,'Uncategorised'), i.description""").fetchall()
    if request.method=="POST":
        invdate=request.form.get("invoice_date") or str(date.today())
        due=request.form.get("due_date") or str(date.today()+timedelta(days=int(setting("terms") or 14)))
        c.execute("""INSERT INTO invoices(number,customer_id,invoice_date,due_date,status,discount,vat_rate,notes)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (next_invoice(),int(request.form["customer_id"]),invdate,due,request.form.get("status","UNPAID"),
                   float(request.form.get("discount") or 0),float(request.form.get("vat_rate") or setting("vat") or 15),request.form.get("notes","")))
        iid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        descs=request.form.getlist("description[]"); qtys=request.form.getlist("qty[]"); prices=request.form.getlist("price[]")
        for d,q,p in zip(descs,qtys,prices):
            if d.strip() and float(q or 0)>0:
                c.execute("INSERT INTO invoice_lines(invoice_id,description,qty,unit_price) VALUES(?,?,?,?)",
                          (iid,d,float(q),float(p or 0)))
        c.commit(); c.close(); return redirect(url_for("view_invoice",iid=iid))
    c.close()
    return render_template("invoice_form.html",customers=customers,items=items,today=str(date.today()),
                           due=str(date.today()+timedelta(days=int(setting("terms") or 14))))

@app.route("/invoice/<int:iid>")
def view_invoice(iid):
    c=db()
    inv=c.execute("""SELECT i.*,c.* FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.id=?""",(iid,)).fetchone()
    lines=c.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id",(iid,)).fetchall()
    c.close()
    if not inv: return "Not found",404
    subtotal,discount,vat,total=totals(iid)
    return render_template("invoice.html",inv=inv,lines=lines,subtotal=subtotal,discount=discount,vat=vat,total=total)

@app.route("/invoice/<int:iid>/print")
def print_invoice(iid):
    c=db()
    inv=c.execute("""SELECT i.*,c.* FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.id=?""",(iid,)).fetchone()
    lines=c.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id""",(iid,)).fetchall()
    c.close()
    if not inv: return "Not found",404
    subtotal,discount,vat,total=totals(iid)
    return render_template("invoice_print.html",inv=inv,lines=lines,subtotal=subtotal,discount=discount,vat=vat,total=total,company=company())

@app.route("/invoice/<int:iid>/paid", methods=["POST"])
def mark_paid(iid):
    c=db(); c.execute("UPDATE invoices SET status='PAID' WHERE id=?",(iid,)); c.commit(); c.close()
    return redirect(url_for("view_invoice",iid=iid))

@app.route("/invoice/<int:iid>/delete", methods=["POST"])
def delete_invoice(iid):
    # Soft delete: the invoice remains stored and its number is never reused.
    c=db()
    c.execute("UPDATE invoices SET deleted=1 WHERE id=?",(iid,))
    c.commit(); c.close()
    flash("Invoice deleted. Its invoice number will not be reused.")
    return redirect(url_for("history"))

@app.route("/history")
def history():
    c=db()
    rows=c.execute("""SELECT i.*,c.name customer FROM invoices i JOIN customers c ON c.id=i.customer_id
                      WHERE COALESCE(i.deleted,0)=0 ORDER BY i.id DESC""").fetchall()
    c.close()
    data=[]
    for r in rows:
        s,d,v,t=totals(r["id"]); data.append((r,s,d,v,t))
    return render_template("history.html",rows=data)


@app.route("/sold")
def sold():
    c = db()
    rows = c.execute(
        "SELECT * FROM sold_items ORDER BY sold_date DESC, id DESC"
    ).fetchall()
    c.close()
    subtotal = sum(float(r["selling_price"] or 0) for r in rows)
    vat = sum(float(r["vat_amount"] or 0) for r in rows)
    total = sum(float(r["total"] or 0) for r in rows)
    profit = sum(float(r["profit"] or 0) for r in rows)
    return render_template(
        "sold.html",
        rows=rows,
        subtotal=subtotal,
        vat=vat,
        total=total,
        profit=profit,
    )

@app.route("/item/<int:item_id>/sold", methods=["POST"])
def mark_item_sold(item_id):
    c = db()
    item = c.execute(
        "SELECT * FROM items WHERE id=? AND active=1", (item_id,)
    ).fetchone()
    if not item:
        c.close()
        flash("Item not found or it has already been sold.")
        return redirect(url_for("items"))

    try:
        selling_price = float(request.form.get("selling_price") or item["price"] or 0)
        cost_price = float(request.form.get("cost_price") or 0)
        vat_rate = float(request.form.get("vat_rate") or setting("vat") or 15)
    except ValueError:
        c.close()
        flash("Please enter valid numeric values.")
        return redirect(url_for("items"))

    vat_amount = selling_price * vat_rate / 100
    total = selling_price + vat_amount
    profit = selling_price - cost_price

    c.execute(
        """INSERT INTO sold_items
           (item_id,description,sold_date,selling_price,vat_rate,vat_amount,total,cost_price,profit)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            item_id,
            item["description"],
            str(date.today()),
            selling_price,
            vat_rate,
            vat_amount,
            total,
            cost_price,
            profit,
        ),
    )
    c.execute("UPDATE items SET active=0 WHERE id=?", (item_id,))
    user_cols = [r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "role" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin'")
    c.commit()
    c.close()
    flash(f"{item['description']} moved to Sold.")
    return redirect(url_for("sold"))

@app.route("/sold/<int:sold_id>/delete", methods=["POST"])
def delete_sold(sold_id):
    c = db()
    sale = c.execute(
        "SELECT item_id FROM sold_items WHERE id=?", (sold_id,)
    ).fetchone()
    if not sale:
        c.close()
        flash("Sold item not found.")
        return redirect(url_for("sold"))

    if sale["item_id"] is not None:
        c.execute("UPDATE items SET active=1 WHERE id=?", (sale["item_id"],))
    c.execute("DELETE FROM sold_items WHERE id=?", (sold_id,))
    c.commit()
    c.close()
    flash("Sale removed and the item returned to Parts & Services.")
    return redirect(url_for("sold"))




def admin_only():
    if "user_id" not in session:
        return False
    c=db(); me=c.execute("SELECT role FROM users WHERE id=?",(session["user_id"],)).fetchone(); c.close()
    return bool(me and me["role"]=="admin")

def employee_record_for_user(user_id):
    c=db(); r=c.execute("SELECT * FROM employees WHERE user_id=? AND active=1",(user_id,)).fetchone(); c.close(); return r

@app.route("/admin/users")
def admin_users():
    if not admin_only(): return redirect(url_for("employee_portal"))
    c=db()
    rows=c.execute("SELECT id, username, role, created_at FROM users WHERE role='admin' ORDER BY username").fetchall()
    c.close()
    return render_template("admin_users.html", rows=rows)

@app.route("/admin/users/add", methods=["POST"])
def admin_users_add():
    if not admin_only(): return redirect(url_for("employee_portal"))
    name=(request.form.get("name") or "").strip()
    email=(request.form.get("email") or "").strip().lower()
    password=(request.form.get("password") or "").strip()
    if not email or not password:
        flash("Administrator email and password are required.")
        return redirect(url_for("admin_users"))
    if len(password) < 6:
        flash("Administrator password must be at least 6 characters.")
        return redirect(url_for("admin_users"))
    c=db()
    try:
        if c.execute("SELECT id FROM users WHERE username=?",(email,)).fetchone():
            flash("That email address is already in use.")
            return redirect(url_for("admin_users"))
        c.execute("INSERT INTO users(username,password_hash,created_at,role) VALUES(?,?,?,?)",
                  (email,generate_password_hash(password),date.today().isoformat(),"admin"))
        c.commit()
        flash(f"Administrator account created for {name or email}.")
    except Exception as exc:
        c.rollback(); flash(f"Could not create administrator: {exc}")
    finally:
        c.close()
    return redirect(url_for("admin_users"))

@app.route("/admin/users/<int:user_id>/update", methods=["POST"])
def admin_users_update(user_id):
    if not admin_only(): return redirect(url_for("employee_portal"))
    email=(request.form.get("email") or "").strip().lower()
    password=(request.form.get("password") or "").strip()
    if not email:
        flash("Administrator email is required.")
        return redirect(url_for("admin_users"))
    if password and len(password) < 6:
        flash("Password must be at least 6 characters.")
        return redirect(url_for("admin_users"))
    c=db()
    try:
        target=c.execute("SELECT * FROM users WHERE id=? AND role='admin'",(user_id,)).fetchone()
        if not target:
            flash("Administrator not found."); return redirect(url_for("admin_users"))
        conflict=c.execute("SELECT id FROM users WHERE username=? AND id!=?",(email,user_id)).fetchone()
        if conflict:
            flash("That email address is already in use."); return redirect(url_for("admin_users"))
        if password:
            c.execute("UPDATE users SET username=?, password_hash=? WHERE id=?",(email,generate_password_hash(password),user_id))
        else:
            c.execute("UPDATE users SET username=? WHERE id=?",(email,user_id))
        c.commit()
        if user_id == session.get("user_id"):
            session.modified=True
        flash("Administrator login details updated.")
    except Exception as exc:
        c.rollback(); flash(f"Could not update administrator: {exc}")
    finally:
        c.close()
    return redirect(url_for("admin_users"))

@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
def admin_users_delete(user_id):
    if not admin_only(): return redirect(url_for("employee_portal"))
    if user_id == session.get("user_id"):
        flash("You cannot delete your own administrator account.")
        return redirect(url_for("admin_users"))
    c=db()
    try:
        count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        target=c.execute("SELECT id FROM users WHERE id=? AND role='admin'",(user_id,)).fetchone()
        if not target:
            flash("Administrator not found.")
        elif count <= 1:
            flash("The last administrator account cannot be deleted.")
        else:
            c.execute("DELETE FROM users WHERE id=?",(user_id,)); c.commit(); flash("Administrator account removed.")
    except Exception as exc:
        c.rollback(); flash(f"Could not remove administrator: {exc}")
    finally:
        c.close()
    return redirect(url_for("admin_users"))

@app.route("/employee-register", methods=["GET","POST"])
def employee_register():
    # Employee accounts are created and controlled by the administrator.
    flash("Employee accounts are created by the administrator. Please use the email and password provided to you.")
    return redirect(url_for("login"))

@app.route("/employees")
def employees_admin():
    if not admin_only(): return redirect(url_for("employee_portal"))
    c=db()
    rows=c.execute("""SELECT e.*, u.username, COALESCE(er.day_rate,0) AS day_rate
                      FROM employees e LEFT JOIN users u ON u.id=e.user_id
                      LEFT JOIN employee_rates er ON er.employee_id=e.id ORDER BY e.full_name""").fetchall()
    c.close(); return render_template("employees.html",rows=rows)

@app.route("/employees/add", methods=["POST"])
def employees_add():
    if not admin_only(): return redirect(url_for("employee_portal"))
    c=db()
    try:
        name=(request.form.get("full_name") or "").strip(); number=(request.form.get("employee_number") or "").strip(); email=(request.form.get("email") or "").strip().lower()
        day=max(0.0,float(request.form.get("day_rate") or 0))
        if not name: flash("Employee name is required."); return redirect(url_for("employees_admin"))
        if not number: number=f"EMP-{int(c.execute('SELECT COALESCE(MAX(id),0)+1 FROM employees').fetchone()[0]):04d}"
        if c.execute("SELECT id FROM employees WHERE employee_number=?",(number,)).fetchone(): flash("That employee number already exists."); return redirect(url_for("employees_admin"))
        password=(request.form.get("password") or "").strip()
        if not email:
            flash("Employee email address is required."); return redirect(url_for("employees_admin"))
        if len(password) < 6:
            flash("Employee password must be at least 6 characters."); return redirect(url_for("employees_admin"))
        existing_email=c.execute("SELECT id FROM users WHERE username=?",(email,)).fetchone()
        if existing_email:
            flash("That email address is already in use."); return redirect(url_for("employees_admin"))
        c.execute("INSERT INTO users(username,password_hash,created_at,role) VALUES(?,?,?,?)",(email,generate_password_hash(password),date.today().isoformat(),"employee"))
        uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO employees(user_id,full_name,employee_number,email,consent_given) VALUES(?,?,?,?,0)",(uid,name,number,email))
        eid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO employee_rates(employee_id,hourly_rate,day_rate) VALUES(?,?,?)",(eid,0,day))
        c.commit(); flash(f"{name} added. Give them the employee registration page and their employee number.")
    except Exception as exc: c.rollback(); flash(f"Could not add employee: {exc}")
    finally: c.close()
    return redirect(url_for("employees_admin"))

@app.route("/employees/<int:employee_id>/credentials", methods=["POST"])
def employee_credentials_update(employee_id):
    if not admin_only(): return redirect(url_for("employee_portal"))
    email=(request.form.get("email") or "").strip().lower()
    password=(request.form.get("password") or "").strip()
    if not email:
        flash("Employee email address is required.")
        return redirect(url_for("employees_admin"))
    if password and len(password) < 6:
        flash("Password must be at least 6 characters.")
        return redirect(url_for("employees_admin"))
    c=db()
    emp=c.execute("SELECT * FROM employees WHERE id=? AND active=1",(employee_id,)).fetchone()
    if not emp:
        c.close(); flash("Employee not found."); return redirect(url_for("employees_admin"))
    conflict=c.execute("SELECT id FROM users WHERE username=? AND id!=?",(email,emp["user_id"] or -1)).fetchone()
    if conflict:
        c.close(); flash("That email address is already in use."); return redirect(url_for("employees_admin"))
    if emp["user_id"]:
        if password:
            c.execute("UPDATE users SET username=?,password_hash=?,role='employee' WHERE id=?",(email,generate_password_hash(password),emp["user_id"]))
        else:
            c.execute("UPDATE users SET username=?,role='employee' WHERE id=?",(email,emp["user_id"]))
        uid=emp["user_id"]
    else:
        if not password:
            c.close(); flash("Enter a new password for this employee."); return redirect(url_for("employees_admin"))
        c.execute("INSERT INTO users(username,password_hash,created_at,role) VALUES(?,?,?,?)",(email,generate_password_hash(password),date.today().isoformat(),"employee"))
        uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("UPDATE employees SET user_id=? WHERE id=?",(uid,employee_id))
    c.execute("UPDATE employees SET email=? WHERE id=?",(email,employee_id))
    c.commit(); c.close()
    flash("Employee login details saved. Give the employee the email and password you set.")
    return redirect(url_for("employees_admin"))

@app.route("/employees/<int:employee_id>/delete", methods=["POST"])
def employee_delete(employee_id):
    if not admin_only():
        return redirect(url_for("employee_portal"))
    c=db()
    try:
        emp=c.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        if not emp:
            c.close(); flash("Employee not found."); return redirect(url_for("employees_admin"))

        # Remove dependent attendance records first because the legacy attendance
        # table does not use ON DELETE CASCADE. Other employee tables do cascade.
        c.execute("DELETE FROM attendance WHERE employee_id=?", (employee_id,))
        c.execute("DELETE FROM employee_attendance_days WHERE employee_id=?", (employee_id,))
        c.execute("DELETE FROM employee_monthly_rates WHERE employee_id=?", (employee_id,))
        c.execute("DELETE FROM employee_rates WHERE employee_id=?", (employee_id,))
        c.execute("DELETE FROM face_samples WHERE employee_id=?", (employee_id,))

        user_id=emp["user_id"]
        c.execute("DELETE FROM employees WHERE id=?", (employee_id,))
        if user_id:
            # Only delete the linked employee login, never an administrator.
            c.execute("DELETE FROM users WHERE id=? AND role='employee'", (user_id,))
        c.commit(); c.close()
        flash(f"Employee {emp['full_name']} was deleted successfully.")
    except Exception as exc:
        c.rollback(); c.close(); flash(f"Could not delete employee: {exc}")
    return redirect(url_for("employees_admin"))

@app.route("/employees/<int:employee_id>/rate", methods=["POST"])
def employee_rate_update(employee_id):
    if not admin_only(): return redirect(url_for("employee_portal"))
    c=db(); day=max(0.0,float(request.form.get("day_rate") or 0))
    c.execute("INSERT INTO employee_rates(employee_id,hourly_rate,day_rate) VALUES(?,?,?) ON CONFLICT(employee_id) DO UPDATE SET day_rate=excluded.day_rate,hourly_rate=0",(employee_id,0,day)); c.commit(); c.close()
    flash("Employee day rate updated."); return redirect(url_for("employees_admin"))

def ensure_day(c, employee_id, work_date):
    c.execute("INSERT OR IGNORE INTO employee_attendance_days(employee_id,work_date,employee_marked,final_worked) VALUES(?,?,0,0)",(employee_id,work_date))
    return c.execute("SELECT * FROM employee_attendance_days WHERE employee_id=? AND work_date=?",(employee_id,work_date)).fetchone()

def effective_day_rate(c, employee_id, month):
    row=c.execute("SELECT day_rate FROM employee_monthly_rates WHERE employee_id=? AND month=?",(employee_id,month)).fetchone()
    if row is not None:
        return float(row["day_rate"] or 0), True
    row=c.execute("SELECT COALESCE(day_rate,0) AS day_rate FROM employee_rates WHERE employee_id=?",(employee_id,)).fetchone()
    return float(row["day_rate"] if row else 0), False

@app.route("/employee")
def employee_portal():
    emp=employee_record_for_user(session.get("user_id"))
    if not emp: return redirect(url_for("login"))
    today=date.today(); month=today.strftime("%Y-%m")
    c=db(); ensure_day(c,emp["id"],today.isoformat())
    r=c.execute("SELECT * FROM employee_attendance_days WHERE employee_id=? AND work_date=?",(emp["id"],today.isoformat())).fetchone()
    days=c.execute("SELECT COUNT(*) AS n FROM employee_attendance_days WHERE employee_id=? AND substr(work_date,1,7)=? AND final_worked=1",(emp["id"],month)).fetchone()["n"]
    c.commit(); c.close()
    return render_template("employee_portal.html",employee=emp,today=today.isoformat(),today_record=r,days_worked=days)

@app.route("/employee/mark-today", methods=["POST"])
def employee_mark_today():
    emp=employee_record_for_user(session.get("user_id"))
    if not emp: return redirect(url_for("login"))
    today=date.today().isoformat(); now=datetime.now().isoformat(timespec="seconds")
    c=db(); ensure_day(c,emp["id"],today)
    c.execute("UPDATE employee_attendance_days SET employee_marked=1, final_worked=1, employee_marked_at=? WHERE employee_id=? AND work_date=?",(now,emp["id"],today)); c.commit(); c.close()
    flash("Today's work attendance has been recorded."); return redirect(url_for("employee_portal"))

@app.route("/employee/attendance")
def employee_attendance():
    emp=employee_record_for_user(session.get("user_id"))
    if not emp: return redirect(url_for("login"))
    month=request.args.get("month") or date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}",month): month=date.today().strftime("%Y-%m")
    c=db(); rows=c.execute("SELECT * FROM employee_attendance_days WHERE employee_id=? AND substr(work_date,1,7)=? ORDER BY work_date",(emp["id"],month)).fetchall()
    rate,_=effective_day_rate(c,emp["id"],month)
    worked=sum(1 for r in rows if r["final_worked"]); total=worked*rate
    c.close(); return render_template("employee_attendance.html",employee=emp,month=month,rows=rows,worked=worked,day_rate=rate,total=total)

@app.route("/employees/attendance")
def employees_attendance():
    if not admin_only(): return redirect(url_for("employee_portal"))
    employee_id=request.args.get("employee_id") or ""; month=request.args.get("month") or date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}",month): month=date.today().strftime("%Y-%m")
    c=db(); employees=c.execute("SELECT id,full_name,employee_number FROM employees WHERE active=1 ORDER BY full_name").fetchall()
    emp=None
    if employee_id.isdigit(): emp=c.execute("SELECT e.*,COALESCE(er.day_rate,0) AS base_day_rate FROM employees e LEFT JOIN employee_rates er ON er.employee_id=e.id WHERE e.id=?",(int(employee_id),)).fetchone()
    rows=[]
    if emp:
        import calendar
        y,m=map(int,month.split('-')); n=calendar.monthrange(y,m)[1]
        for d in range(1,n+1):
            wd=date(y,m,d).isoformat(); rec=ensure_day(c,emp["id"],wd)
            rows.append(rec)
        c.commit()
    rate,has_override=effective_day_rate(c,emp["id"],month) if emp else (0,False)
    worked=sum(1 for r in rows if r["final_worked"]); total=worked*rate
    c.close(); return render_template("attendance_admin.html",employees=employees,employee=emp,month=month,rows=rows,worked=worked,day_rate=rate,has_rate_override=has_override,total=total)

@app.route("/employees/attendance/set/<int:employee_id>/<work_date>", methods=["POST"])
def admin_set_worked(employee_id,work_date):
    if not admin_only(): return redirect(url_for("employee_portal"))
    try: date.fromisoformat(work_date)
    except ValueError: flash("Invalid date."); return redirect(url_for("employees_attendance"))
    status=1 if request.form.get("worked") == "1" else 0; now=datetime.now().isoformat(timespec="seconds")
    c=db(); ensure_day(c,employee_id,work_date); c.execute("UPDATE employee_attendance_days SET final_worked=?,admin_updated_at=?,admin_updated_by=? WHERE employee_id=? AND work_date=?",(status,now,session["user_id"],employee_id,work_date)); c.commit(); c.close()
    return redirect(url_for("employees_attendance",employee_id=employee_id,month=work_date[:7]))

@app.route("/employees/attendance/rate", methods=["POST"])
def employee_monthly_rate_update():
    if not admin_only(): return redirect(url_for("employee_portal"))
    employee_id=request.form.get("employee_id","")
    month=request.form.get("month","")
    if not employee_id.isdigit() or not re.fullmatch(r"\d{4}-\d{2}",month):
        flash("Invalid employee or month."); return redirect(url_for("employees_attendance"))
    action=request.form.get("action","save")
    c=db()
    if action=="reset":
        c.execute("DELETE FROM employee_monthly_rates WHERE employee_id=? AND month=?",(int(employee_id),month))
        c.commit(); c.close(); flash("Monthly day rate reset to the employee's standard day rate.")
    else:
        try: rate=max(0.0,float(request.form.get("day_rate") or 0))
        except ValueError: rate=0.0
        now=datetime.now().isoformat(timespec="seconds")
        c.execute("INSERT INTO employee_monthly_rates(employee_id,month,day_rate,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(employee_id,month) DO UPDATE SET day_rate=excluded.day_rate,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(int(employee_id),month,rate,now,session["user_id"]))
        c.commit(); c.close(); flash(f"Monthly day rate saved at R {rate:,.2f}.")
    return redirect(url_for("employees_attendance",employee_id=employee_id,month=month))

@app.route("/employees/report")
def employee_report():
    if not admin_only(): return redirect(url_for("employee_portal"))
    employee_id=request.args.get("employee_id") or ""; month=request.args.get("month") or date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}",month): month=date.today().strftime("%Y-%m")
    c=db(); employees=c.execute("SELECT id,full_name,employee_number FROM employees WHERE active=1 ORDER BY full_name").fetchall(); emp=None; rows=[]
    if employee_id.isdigit():
        emp=c.execute("SELECT e.*,COALESCE(er.day_rate,0) AS base_day_rate FROM employees e LEFT JOIN employee_rates er ON er.employee_id=e.id WHERE e.id=?",(int(employee_id),)).fetchone()
    if emp:
        import calendar
        y,m=map(int,month.split('-')); n=calendar.monthrange(y,m)[1]
        for d in range(1,n+1): rows.append(ensure_day(c,emp["id"],date(y,m,d).isoformat()))
        c.commit()
    rate,has_override=effective_day_rate(c,emp["id"],month) if emp else (0,False)
    worked=sum(1 for r in rows if r["final_worked"]); total=worked*rate
    c.close(); return render_template("employee_report.html",employees=employees,employee=emp,month=month,rows=rows,worked=worked,day_rate=rate,has_rate_override=has_override,total=total)

@app.route("/employees/attendance/edit/<int:attendance_id>", methods=["POST"])
def edit_attendance(attendance_id):
    if not admin_only(): return redirect(url_for("employee_portal"))
    return redirect(url_for("employees_attendance"))

@app.route("/employees/attendance/delete/<int:attendance_id>", methods=["POST"])
def delete_attendance(attendance_id):
    if not admin_only(): return redirect(url_for("employee_portal"))
    c=db(); c.execute("DELETE FROM employee_attendance_days WHERE id=?",(attendance_id,)); c.commit(); c.close(); flash("Attendance day cleared."); return redirect(url_for("employees_attendance"))

@app.route("/settings", methods=["GET","POST"])
def settings():
    if request.method=="POST":
        c=db()
        for k in COMPANY_DEFAULTS:
            if k in request.form:
                c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k,request.form[k]))
        c.commit(); c.close(); flash("Settings saved.")
    return render_template("settings.html",s=company())

@app.route("/backup")
def backup():
    """Create ONE complete Dirt Dynamics data backup file."""
    init_db()
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    out=os.path.join(tempfile.gettempdir(), f"dirt_dynamics_complete_backup_{stamp}.ddbackup")
    manifest={
        "format":"Dirt Dynamics Complete Backup",
        "version":1,
        "created_at":datetime.now().isoformat(timespec="seconds"),
        "database":"dirt_dynamics.db",
        "includes":"All business database data: invoices, customers, inventory, categories, sold items, employees, employee accounts, attendance, rates and settings."
    }
    # SQLite backup API makes a consistent copy even while the application is running.
    src=sqlite3.connect(DB_PATH)
    dst=sqlite3.connect(out + ".tmp.db")
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.write(out + ".tmp.db", "dirt_dynamics.db")
        z.writestr("backup_manifest.json", json.dumps(manifest, indent=2))
    os.remove(out + ".tmp.db")
    return send_file(out, as_attachment=True, download_name=f"Dirt_Dynamics_COMPLETE_Backup_{stamp}.ddbackup", mimetype="application/octet-stream")

@app.route("/backup/restore", methods=["POST"])
def restore_backup():
    """Restore a complete Dirt Dynamics .ddbackup file after validating it."""
    if not admin_only(): return redirect(url_for("employee_portal"))
    uploaded=request.files.get("backup_file")
    if not uploaded or not uploaded.filename:
        flash("Please select a Dirt Dynamics backup file.")
        return redirect(url_for("backup_restore"))
    filename=secure_filename(uploaded.filename)
    if not filename.lower().endswith(".ddbackup"):
        flash("Invalid backup file. Please choose a .ddbackup file created by Dirt Dynamics.")
        return redirect(url_for("backup_restore"))
    work=tempfile.mkdtemp(prefix="dd_restore_")
    try:
        incoming=os.path.join(work,filename)
        uploaded.save(incoming)
        with zipfile.ZipFile(incoming,"r") as z:
            names=set(z.namelist())
            if "dirt_dynamics.db" not in names or "backup_manifest.json" not in names:
                raise ValueError("The backup file is incomplete or not a Dirt Dynamics backup.")
            z.extract("dirt_dynamics.db",work)
            manifest=json.loads(z.read("backup_manifest.json").decode("utf-8"))
            if manifest.get("format") != "Dirt Dynamics Complete Backup":
                raise ValueError("This backup was not created by the Dirt Dynamics system.")
        candidate=os.path.join(work,"dirt_dynamics.db")
        test=sqlite3.connect(candidate)
        try:
            ok=test.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok": raise ValueError("The backup database failed its integrity check.")
            required={"users","customers","items","invoices","invoice_lines","employees","employee_rates","sold_items","settings","employee_attendance_days","employee_monthly_rates"}
            found={r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            missing=required-found
            if missing: raise ValueError("The backup is missing required Dirt Dynamics data tables.")
        finally:
            test.close()

        # Always make a safety copy of the current database before replacing it.
        safety=os.path.join(tempfile.gettempdir(), f"dirt_dynamics_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        if os.path.exists(DB_PATH): shutil.copy2(DB_PATH,safety)
        # The uploaded backup is extracted under /tmp on hosted platforms such as Render.
        # Do not os.replace() it directly into DB_PATH: /tmp and the app directory
        # can be different filesystems, which causes Errno 18 (cross-device link).
        # First copy the validated database onto the same filesystem as DB_PATH,
        # then atomically replace the live database from there.
        restore_tmp = DB_PATH + f".restore_tmp_{secrets.token_hex(6)}"
        try:
            shutil.copy2(candidate, restore_tmp)
            os.replace(restore_tmp, DB_PATH)
        finally:
            if os.path.exists(restore_tmp):
                try: os.remove(restore_tmp)
                except OSError: pass
        flash("Complete backup restored successfully. Invoices, employees, inventory and all other saved business data have been restored.")
    except Exception as e:
        flash(f"Restore failed: {e}")
    finally:
        shutil.rmtree(work,ignore_errors=True)
    return redirect(url_for("backup_restore"))

@app.route("/backup/restore", methods=["GET"])
def backup_restore():
    if not admin_only(): return redirect(url_for("employee_portal"))
    return render_template("backup.html")

@app.route("/api/status")
def api_status():
    return jsonify({"ok":True,"company":company()["name"]})

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
