# Dirt Dynamics Invoice System

This version keeps the existing invoicing, customers, parts/services, sold items, settings and history functions, and replaces the employee time clock with a simple daily attendance system.

## Employee portal
- Each employee has a personal account.
- Administrator creates each employee account with their email and password.
- Employee logs in and presses **I WORKED TODAY**.
- Employee can view their own monthly attendance.
- Employees cannot edit their attendance or see other employees.

## Admin portal
- Add employee with name, employee number, email and day rate.
- Select an employee and any month.
- See every calendar day for that month.
- See whether the employee marked the day as worked.
- Admin can change the final status between WORKED and NOT WORKED.
- Monthly pay is calculated as days worked x day rate.
- Generate a print/save-as-PDF monthly report showing employee-submitted status, final admin status, days worked, day rate and total pay.

## Registration
After an employee is added by the administrator, the employee receives the email and password set by the administrator and uses the normal login page.


## Database persistence
When deployed to Render with a Persistent Disk mounted at `/var/data`, the application stores `dirt_dynamics.db` on that disk. On first deployment, if an existing local database is present and the persistent-disk database does not yet exist, it is copied to the persistent disk automatically.
