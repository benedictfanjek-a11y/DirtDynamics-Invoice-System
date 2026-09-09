from flask import render_template, request, redirect, url_for, flash
import app as _a


def _ensure_qty(c):
    cols = [r["name"] for r in c.execute("PRAGMA table_info(items)").fetchall()]
    if "qty" not in cols:
        c.execute("ALTER TABLE items ADD COLUMN qty REAL NOT NULL DEFAULT 0")
        c.commit()


def _redirect_items(category=None):
    return redirect(url_for("items", category=category or request.args.get("category", "all")))


def edit_item(item_id):
    c = _a.db()
    try:
        _ensure_qty(c)
        item = c.execute("SELECT * FROM items WHERE id=? AND active=1", (item_id,)).fetchone()
        if not item:
            flash("Part not found.")
            return _redirect_items()
        if request.method == "POST":
            try:
                category_id = request.form.get("category_id") or None
                category_id = int(category_id) if category_id else None
                description = (request.form.get("description") or "").strip()
                code = (request.form.get("code") or "").strip()
                unit = (request.form.get("unit") or "each").strip() or "each"
                qty = max(0.0, float(request.form.get("qty") or 0))
                price = max(0.0, float(request.form.get("price") or 0))
                if not description:
                    raise ValueError("Part description is required.")
                if category_id is not None and not c.execute("SELECT id FROM item_categories WHERE id=? AND active=1", (category_id,)).fetchone():
                    raise ValueError("Selected category was not found.")
                c.execute("UPDATE items SET code=?,description=?,price=?,unit=?,qty=?,category_id=? WHERE id=?",
                          (code, description, price, unit, qty, category_id, item_id))
                c.commit()
                flash(f"{description} updated. Price: R {price:,.2f} per {unit}. Stock: {qty:g} {unit}.")
                return _redirect_items(request.form.get("category") or request.args.get("category") or (str(category_id) if category_id else "all"))
            except (ValueError, TypeError) as exc:
                c.rollback(); flash(str(exc))
                return redirect(url_for("edit_item", item_id=item_id, category=request.args.get("category", "all")))
            except Exception as exc:
                c.rollback(); flash(f"Could not update part: {exc}")
                return redirect(url_for("edit_item", item_id=item_id, category=request.args.get("category", "all")))
        categories = c.execute("SELECT id,name FROM item_categories WHERE active=1 ORDER BY name").fetchall()
        return render_template("item_edit.html", item=item, categories=categories)
    finally:
        c.close()


def adjust_stock(item_id):
    c = _a.db()
    try:
        _ensure_qty(c)
        item = c.execute("SELECT * FROM items WHERE id=? AND active=1", (item_id,)).fetchone()
        if not item:
            flash("Part not found.")
            return _redirect_items()
        try:
            mode = request.form.get("mode", "set")
            if mode == "add":
                amount = float(request.form.get("amount") or 0)
                if amount < 0: raise ValueError
                new_qty = float(item["qty"] or 0) + amount
            elif mode == "subtract":
                amount = float(request.form.get("amount") or 0)
                if amount < 0: raise ValueError
                new_qty = max(0.0, float(item["qty"] or 0) - amount)
            else:
                new_qty = float(request.form.get("qty") or 0)
                if new_qty < 0: raise ValueError
            c.execute("UPDATE items SET qty=? WHERE id=?", (new_qty, item_id))
            c.commit()
            flash(f"{item['description']} stock updated to {new_qty:g} {item['unit'] or 'each'}.")
        except (ValueError, TypeError):
            c.rollback(); flash("Please enter a valid stock quantity.")
        except Exception as exc:
            c.rollback(); flash(f"Could not adjust stock: {exc}")
        return _redirect_items()
    finally:
        c.close()


def wrap_items(original):
    """Keep the existing /items handler while persisting its new qty field."""
    def wrapped():
        if request.method == "POST" and request.form.get("action", "add_item") == "add_item":
            c = _a.db()
            _ensure_qty(c)
            before_id = int(c.execute("SELECT COALESCE(MAX(id),0) AS id FROM items").fetchone()["id"] or 0)
            c.close()
            response = original()
            try:
                qty = max(0.0, float(request.form.get("qty") or 0))
                c = _a.db(); _ensure_qty(c)
                row = c.execute("SELECT id FROM items WHERE id>? ORDER BY id DESC LIMIT 1", (before_id,)).fetchone()
                if row:
                    c.execute("UPDATE items SET qty=? WHERE id=?", (qty, row["id"]))
                    c.commit()
                c.close()
            except (ValueError, TypeError):
                pass
            return response
        return original()
    wrapped.__name__ = "items"
    return wrapped


# These routes are also registered here for deployments where the inventory
# loader is imported directly rather than through gunicorn.conf.py.
_c = _a.db()
try:
    _ensure_qty(_c)
finally:
    _c.close()
if "edit_item" not in _a.app.view_functions:
    _a.app.add_url_rule("/item/<int:item_id>/edit", endpoint="edit_item", view_func=edit_item, methods=["GET", "POST"])
if "adjust_stock" not in _a.app.view_functions:
    _a.app.add_url_rule("/item/<int:item_id>/stock", endpoint="adjust_stock", view_func=adjust_stock, methods=["POST"])
