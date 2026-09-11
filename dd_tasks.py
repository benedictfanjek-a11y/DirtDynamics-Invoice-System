from datetime import date, datetime
from flask import render_template, request, redirect, url_for, flash
import app as _a


def _ensure_tasks(c):
    c.execute("""CREATE TABLE IF NOT EXISTS employee_tasks(
        id INTEGER PRIMARY KEY,
        employee_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        due_date TEXT,
        priority TEXT NOT NULL DEFAULT 'Normal',
        notes TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'PENDING',
        completed_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_employee_tasks_employee_status ON employee_tasks(employee_id,status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_employee_tasks_due_date ON employee_tasks(due_date)")
    c.commit()


def _admin_redirect():
    return redirect(url_for("employee_tasks"))


def employee_tasks():
    if not _a.admin_only():
        return redirect(url_for("employee_portal"))
    c = _a.db()
    try:
        _ensure_tasks(c)
        employees = c.execute("SELECT id,full_name,employee_number FROM employees WHERE active=1 ORDER BY full_name").fetchall()
        selected_employee = request.args.get("employee_id", "")
        selected_status = request.args.get("status", "")
        sql = """SELECT t.*, e.full_name, e.employee_number
                 FROM employee_tasks t JOIN employees e ON e.id=t.employee_id
                 WHERE e.active=1"""
        params = []
        if selected_employee.isdigit():
            sql += " AND t.employee_id=?"; params.append(int(selected_employee))
        if selected_status in ("PENDING", "COMPLETED"):
            sql += " AND t.status=?"; params.append(selected_status)
        sql += " ORDER BY CASE WHEN t.status='PENDING' THEN 0 ELSE 1 END, CASE WHEN t.due_date IS NULL OR t.due_date='' THEN 1 ELSE 0 END, t.due_date, t.id DESC"
        tasks = c.execute(sql, params).fetchall()
        return render_template("employee_tasks.html", tasks=tasks, employees=employees,
                               selected_employee=selected_employee, selected_status=selected_status)
    finally:
        c.close()


def employee_task_add():
    if not _a.admin_only():
        return redirect(url_for("employee_portal"))
    description = (request.form.get("description") or "").strip()
    employee_id = request.form.get("employee_id") or ""
    due_date = (request.form.get("due_date") or "").strip()
    priority = (request.form.get("priority") or "Normal").strip().title()
    notes = (request.form.get("notes") or "").strip()
    if priority not in ("Low", "Normal", "High"):
        priority = "Normal"
    if not description or not employee_id.isdigit():
        flash("Task description and employee are required.")
        return _admin_redirect()
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError:
            flash("Please enter a valid due date.")
            return _admin_redirect()
    c = _a.db()
    try:
        emp = c.execute("SELECT id,full_name FROM employees WHERE id=? AND active=1", (int(employee_id),)).fetchone()
        if not emp:
            flash("Selected employee was not found.")
            return _admin_redirect()
        now = datetime.now().isoformat(timespec="seconds")
        c.execute("INSERT INTO employee_tasks(employee_id,description,due_date,priority,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                  (emp["id"], description, due_date or None, priority, notes, "PENDING", now, now))
        c.commit()
        flash(f"Task assigned to {emp['full_name']}.")
    except Exception as exc:
        c.rollback(); flash(f"Could not create task: {exc}")
    finally:
        c.close()
    return _admin_redirect()


def employee_task_edit(task_id):
    if not _a.admin_only():
        return redirect(url_for("employee_portal"))
    c = _a.db()
    try:
        _ensure_tasks(c)
        task = c.execute("SELECT * FROM employee_tasks WHERE id=?", (task_id,)).fetchone()
        employees = c.execute("SELECT id,full_name,employee_number FROM employees WHERE active=1 ORDER BY full_name").fetchall()
        if not task:
            flash("Task not found.")
            return _admin_redirect()
        if request.method == "GET":
            return render_template("employee_task_edit.html", task=task, employees=employees)
        description = (request.form.get("description") or "").strip()
        employee_id = request.form.get("employee_id") or ""
        due_date = (request.form.get("due_date") or "").strip()
        priority = (request.form.get("priority") or "Normal").strip().title()
        notes = (request.form.get("notes") or "").strip()
        if not description or not employee_id.isdigit():
            flash("Task description and employee are required.")
            return redirect(url_for("employee_task_edit", task_id=task_id))
        if due_date:
            try: date.fromisoformat(due_date)
            except ValueError:
                flash("Please enter a valid due date.")
                return redirect(url_for("employee_task_edit", task_id=task_id))
        if priority not in ("Low", "Normal", "High"): priority = "Normal"
        emp = c.execute("SELECT id FROM employees WHERE id=? AND active=1", (int(employee_id),)).fetchone()
        if not emp:
            flash("Selected employee was not found.")
            return redirect(url_for("employee_task_edit", task_id=task_id))
        c.execute("UPDATE employee_tasks SET employee_id=?,description=?,due_date=?,priority=?,notes=?,updated_at=? WHERE id=?",
                  (int(employee_id), description, due_date or None, priority, notes, datetime.now().isoformat(timespec="seconds"), task_id))
        c.commit(); flash("Task updated.")
        return _admin_redirect()
    except Exception as exc:
        c.rollback(); flash(f"Could not update task: {exc}")
        return redirect(url_for("employee_task_edit", task_id=task_id))
    finally:
        c.close()


def employee_task_delete(task_id):
    if not _a.admin_only():
        return redirect(url_for("employee_portal"))
    c = _a.db()
    try:
        _ensure_tasks(c)
        c.execute("DELETE FROM employee_tasks WHERE id=?", (task_id,))
        c.commit(); flash("Task deleted.")
    except Exception as exc:
        c.rollback(); flash(f"Could not delete task: {exc}")
    finally:
        c.close()
    return _admin_redirect()


def employee_task_toggle(task_id):
    emp = _a.employee_record_for_user(_a.session.get("user_id"))
    if not emp:
        return redirect(url_for("login"))
    c = _a.db()
    try:
        _ensure_tasks(c)
        task = c.execute("SELECT * FROM employee_tasks WHERE id=? AND employee_id=?", (task_id, emp["id"])).fetchone()
        if not task:
            flash("Task not found.")
            return redirect(url_for("employee_portal"))
        now = datetime.now().isoformat(timespec="seconds")
        if task["status"] == "COMPLETED":
            c.execute("UPDATE employee_tasks SET status='PENDING',completed_at=NULL,updated_at=? WHERE id=?", (now, task_id))
        else:
            c.execute("UPDATE employee_tasks SET status='COMPLETED',completed_at=?,updated_at=? WHERE id=?", (now, now, task_id))
        c.commit()
    except Exception as exc:
        c.rollback(); flash(f"Could not update task: {exc}")
    finally:
        c.close()
    return redirect(url_for("employee_portal"))


def employee_portal_with_tasks():
    emp = _a.employee_record_for_user(_a.session.get("user_id"))
    if not emp:
        return redirect(url_for("login"))
    today = date.today()
    month = today.strftime("%Y-%m")
    c = _a.db()
    try:
        _a.ensure_day(c, emp["id"], today.isoformat())
        record = c.execute("SELECT * FROM employee_attendance_days WHERE employee_id=? AND work_date=?", (emp["id"], today.isoformat())).fetchone()
        days = c.execute("SELECT COUNT(*) AS n FROM employee_attendance_days WHERE employee_id=? AND substr(work_date,1,7)=? AND final_worked=1", (emp["id"], month)).fetchone()["n"]
        _ensure_tasks(c)
        tasks = c.execute("SELECT * FROM employee_tasks WHERE employee_id=? ORDER BY CASE WHEN status='PENDING' THEN 0 ELSE 1 END, CASE WHEN due_date IS NULL OR due_date='' THEN 1 ELSE 0 END, due_date, id DESC", (emp["id"],)).fetchall()
        c.commit()
        return render_template("employee_portal.html", employee=emp, today=today.isoformat(), today_record=record, days_worked=days, tasks=tasks)
    finally:
        c.close()


_c = _a.db()
try:
    _ensure_tasks(_c)
finally:
    _c.close()

if "employee_tasks" not in _a.app.view_functions:
    _a.app.add_url_rule("/employees/tasks", endpoint="employee_tasks", view_func=employee_tasks, methods=["GET"])
if "employee_task_add" not in _a.app.view_functions:
    _a.app.add_url_rule("/employees/tasks/add", endpoint="employee_task_add", view_func=employee_task_add, methods=["POST"])
if "employee_task_edit" not in _a.app.view_functions:
    _a.app.add_url_rule("/employees/tasks/<int:task_id>/edit", endpoint="employee_task_edit", view_func=employee_task_edit, methods=["GET", "POST"])
if "employee_task_delete" not in _a.app.view_functions:
    _a.app.add_url_rule("/employees/tasks/<int:task_id>/delete", endpoint="employee_task_delete", view_func=employee_task_delete, methods=["POST"])
if "employee_task_toggle" not in _a.app.view_functions:
    _a.app.add_url_rule("/employee/tasks/<int:task_id>/toggle", endpoint="employee_task_toggle", view_func=employee_task_toggle, methods=["POST"])
