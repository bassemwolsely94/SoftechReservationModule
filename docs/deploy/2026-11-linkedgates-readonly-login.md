# Linked Gates: read-only database access for the attendance program

**For:** our IT person
**PC:** 192.168.5.43, the one that runs the Linked Gates HR website
**Purpose:** our attendance program will run on this PC and read the Linked Gates punches, to compare them with its own collection. It never changes anything in Linked Gates or on the fingerprint machines.

## 1. Find two names
Open **SQL Server Management Studio** on 192.168.5.43, or **SQL Server Configuration Manager** if SSMS isn't installed.

- **Server / instance name** is shown in the connect dialog, for example `.\SQLEXPRESS` or `192.168.5.43\LINKEDGATES`.
- **Database name** is listed under *Databases* and is usually something like `Linked_ERP_HR_v1`. To confirm it, look in the website's `web.config` file under `connectionStrings`. The website's folder is shown in IIS Manager → the site → *Explore*.

Do **not** send the password that appears in `web.config`. We only need the database name.

## 2. Create the read-only access
Pick **A** if you can. It needs no password at all.

**A. Windows account (preferred).** Choose the Windows account that will run our attendance program on this PC. A dedicated local account such as `elr-attendance` is cleanest. Then run the script below, replacing the account name and the database name:

```sql
USE [master];
CREATE LOGIN [192-168-5-43-PC-NAME\elr-attendance] FROM WINDOWS;
USE [Linked_ERP_HR_v1];   -- the database name from step 1
CREATE USER [elr_attendance] FOR LOGIN [192-168-5-43-PC-NAME\elr-attendance];
ALTER ROLE db_datareader ADD MEMBER [elr_attendance];
DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER TO [elr_attendance];
```

**B. SQL login, only if A isn't possible:**

```sql
USE [master];
CREATE LOGIN [elr_attendance_ro] WITH PASSWORD = '<choose a strong one>', CHECK_POLICY = ON;
USE [Linked_ERP_HR_v1];
CREATE USER [elr_attendance_ro] FOR LOGIN [elr_attendance_ro];
ALTER ROLE db_datareader ADD MEMBER [elr_attendance_ro];
DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER TO [elr_attendance_ro];
```

Keep the password on that PC. Do not email it or paste it into chat. It will go straight into the program's settings file when the program is installed.

**Then hide the private columns from it.** Replace the user name if you used B:

```sql
DENY SELECT ON dbo.Employee (Salary, Phone, Email, EmployeeImage) TO [elr_attendance];
DENY SELECT ON dbo.Users TO [elr_attendance];
DENY SELECT ON dbo.UserPermissions TO [elr_attendance];
DENY SELECT ON dbo.Device (Password) TO [elr_attendance];
```

**Leave the network settings as they are.** Our program runs on the same PC, so the database doesn't need to be opened to the network.

## 3. Send back (no passwords, no employee data)
1. The instance name and the database name.
2. Which option you used (A or B) and the login name.
3. The output of this query, run in the Linked Gates database. It lists table and column names only, with row counts, and contains no employee data:

```sql
SELECT t.name AS table_name, c.name AS column_name, ty.name AS type,
       (SELECT SUM(p.rows) FROM sys.partitions p
         WHERE p.object_id = t.object_id AND p.index_id IN (0,1)) AS row_count
FROM sys.tables t
JOIN sys.columns c  ON c.object_id = t.object_id
JOIN sys.types   ty ON ty.user_type_id = c.user_type_id
ORDER BY t.name, c.column_id;
```

To save it, right-click the result grid → *Save Results As…* → CSV.
4. The SQL Server version (`SELECT @@VERSION;`).

## Check that it is read-only
Log in as the new account and try:

```sql
UPDATE <any table> SET <any column> = <any column> WHERE 1 = 0;
```

It must fail with a "permission denied" error. If it doesn't fail, stop and tell us.
