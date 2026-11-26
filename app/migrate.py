"""Upgrade a database from the one-site-per-client schema.

SQLAlchemy creates new tables, but it does not change columns on tables that
already exist. An older database stores the site name on the client and points
devices and months at that client. This moves each of those clients to one
site so the app can keep the records.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def migrate(engine: Engine) -> None:
    # foreign_keys must be switched outside a transaction, or SQLite ignores it.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if not _has_column(conn, "devices", "client_id"):
            return
        _ensure_sites(conn)
        _rebuild_devices(conn)
        if _has_column(conn, "checks", "client_id"):
            _rebuild_checks(conn)
        if _has_column(conn, "issues", "client_id"):
            _rebuild_issues(conn)


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _ensure_sites(conn) -> None:
    clients = conn.execute(text("SELECT id, site FROM clients")).fetchall()
    for client_id, site_name in clients:
        found = conn.execute(
            text("SELECT id FROM sites WHERE customer_id = :client_id LIMIT 1"),
            {"client_id": client_id},
        ).first()
        if found:
            continue
        conn.execute(
            text("INSERT INTO sites (customer_id, name) VALUES (:client_id, :name)"),
            {"client_id": client_id, "name": site_name or "Site"},
        )


def _rebuild_devices(conn) -> None:
    if not _has_column(conn, "devices", "site_id"):
        conn.execute(text("ALTER TABLE devices ADD COLUMN site_id INTEGER"))
    conn.execute(
        text(
            """
            UPDATE devices
            SET site_id = (
                SELECT sites.id FROM sites
                WHERE sites.customer_id = devices.client_id
                ORDER BY sites.id
                LIMIT 1
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE devices_new (
                id INTEGER PRIMARY KEY,
                site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                device_type VARCHAR(20) NOT NULL,
                name VARCHAR(200) NOT NULL,
                model VARCHAR(200),
                serial_no VARCHAR(200),
                ip_address VARCHAR(100),
                firmware VARCHAR(100),
                warranty_expiry DATE,
                added_on DATE NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO devices_new (
                id, site_id, device_type, name, model, serial_no, ip_address,
                firmware, warranty_expiry, added_on, sort_order, created_at
            )
            SELECT
                id, site_id, device_type, name, model, serial_no, ip_address,
                firmware, warranty_expiry, added_on, sort_order, created_at
            FROM devices
            """
        )
    )
    conn.execute(text("DROP TABLE devices"))
    conn.execute(text("ALTER TABLE devices_new RENAME TO devices"))
    conn.execute(text("CREATE INDEX ix_devices_site_id ON devices (site_id)"))


def _rebuild_checks(conn) -> None:
    if not _has_column(conn, "checks", "site_id"):
        conn.execute(text("ALTER TABLE checks ADD COLUMN site_id INTEGER"))
    conn.execute(
        text(
            """
            UPDATE checks
            SET site_id = (
                SELECT sites.id FROM sites
                WHERE sites.customer_id = checks.client_id
                ORDER BY sites.id
                LIMIT 1
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE checks_new (
                id INTEGER PRIMARY KEY,
                site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                check_date DATE NOT NULL,
                year_month VARCHAR(7) NOT NULL,
                engineer VARCHAR(100) NOT NULL,
                connection_method VARCHAR(20) NOT NULL,
                duration_hours FLOAT,
                notes TEXT,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_site_month UNIQUE (site_id, year_month)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO checks_new (
                id, site_id, check_date, year_month, engineer, connection_method,
                duration_hours, notes, created_at
            )
            SELECT
                id, site_id, check_date, year_month, engineer, connection_method,
                duration_hours, notes, created_at
            FROM checks
            """
        )
    )
    conn.execute(text("DROP TABLE checks"))
    conn.execute(text("ALTER TABLE checks_new RENAME TO checks"))
    conn.execute(text("CREATE INDEX ix_checks_site_id ON checks (site_id)"))


def _rebuild_issues(conn) -> None:
    if not _has_column(conn, "issues", "site_id"):
        conn.execute(text("ALTER TABLE issues ADD COLUMN site_id INTEGER"))
    conn.execute(
        text(
            """
            UPDATE issues
            SET site_id = (
                SELECT sites.id FROM sites
                WHERE sites.customer_id = issues.client_id
                ORDER BY sites.id
                LIMIT 1
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE issues_new (
                id INTEGER PRIMARY KEY,
                site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                code VARCHAR(20) NOT NULL,
                first_found_date DATE NOT NULL,
                source VARCHAR(20) NOT NULL,
                related_label VARCHAR(300),
                device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
                summary TEXT NOT NULL,
                status VARCHAR(10) NOT NULL,
                action TEXT,
                close_date DATE,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_site_issue_code UNIQUE (site_id, code)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO issues_new (
                id, site_id, code, first_found_date, source, related_label, device_id,
                summary, status, action, close_date, created_at
            )
            SELECT
                id, site_id, code, first_found_date, source, related_label, device_id,
                summary, status, action, close_date, created_at
            FROM issues
            """
        )
    )
    conn.execute(text("DROP TABLE issues"))
    conn.execute(text("ALTER TABLE issues_new RENAME TO issues"))
    conn.execute(text("CREATE INDEX ix_issues_site_id ON issues (site_id)"))
