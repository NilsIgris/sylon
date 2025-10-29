#!/bin/bash
set -e  # Stop on first error

# === Install Python and dependencies ===
echo "=== Installing Python and Flask dependencies ==="
apt-get update -y
apt-get install -y python3-pip postgresql postgresql-contrib
pip3 install --break-system-packages flask psycopg2-binary gunicorn

# === Deploy Sylon API ===
echo "=== Deploying Sylon API ==="
mkdir -p /opt/sylon-api
mv ./sylon-api.py /opt/sylon-api/
mv ./sylon-api.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now sylon-api

# Optional pause for user input
read -n1 -r -p "Press any key to continue with database setup..." key
echo

# === PostgreSQL Setup ===
DB_USER="sylon"
DB_PASS="sylon"
DB_NAME="machinedb"

echo "=== Configuring PostgreSQL ==="
systemctl enable postgresql
systemctl start postgresql

echo "=== Creating user and database ==="
runuser -u postgres -- psql <<EOF
DO
\$do\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
      CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS';
   END IF;
END
\$do\$;

CREATE DATABASE $DB_NAME OWNER $DB_USER;
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF

echo "=== Creating table machine_metrics ==="
runuser -u postgres -- psql -d $DB_NAME <<'EOF'
CREATE TABLE IF NOT EXISTS machine_metrics (
  id BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  hostname TEXT,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS machine_metrics_machine_id_idx ON machine_metrics (machine_id);
CREATE INDEX IF NOT EXISTS machine_metrics_ts_idx ON machine_metrics (ts);
EOF

echo "✅ Installation complete! Sylon API and PostgreSQL are ready."
