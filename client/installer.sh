#!/bin/bash
set -e  # Stop on first error

# === Detect Environment ===
detect_env() {
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
      ubuntu)
        echo "ubuntu"
        ;;
      debian)
        echo "debian"
        ;;
      *)
        echo "unknown"
        ;;
    esac
  else
    echo "unknown"
  fi
}

# === Run as postgres user, depending on OS ===
exec_psql() {
  local sql="$1"
  if [ "$ENV" = "ubuntu" ]; then
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "$sql"
  elif [ "$ENV" = "debian" ]; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "$sql"
  else
    echo "❌ Unsupported OS — only Debian and Ubuntu are supported."
    exit 1
  fi
}

exec_psql_file() {
  local db="$1"
  local sql_file="$2"
  if [ "$ENV" = "ubuntu" ]; then
    sudo -u postgres psql -d "$db" -v ON_ERROR_STOP=1 -f "$sql_file"
  elif [ "$ENV" = "debian" ]; then
    runuser -u postgres -- psql -d "$db" -v ON_ERROR_STOP=1 -f "$sql_file"
  fi
}

# === Detect environment ===
ENV=$(detect_env)
echo "=== Detected environment: $ENV ==="

# === Install dependencies ===
echo "=== Installing Python, PostgreSQL, and dependencies ==="
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

read -n1 -r -p "Press any key to continue with database setup..." key
echo

# === PostgreSQL Setup ===
DB_USER="sylon"
DB_PASS="sylon"
DB_NAME="machinedb"

echo "=== Starting PostgreSQL service ==="
systemctl enable postgresql
systemctl start postgresql

echo "=== Creating user and database ==="
USER_SQL=$(cat <<EOF
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
)
exec_psql "$USER_SQL"

echo "=== Creating table machine_metrics ==="
TABLE_SQL_FILE=$(mktemp)
cat <<'EOF' > "$TABLE_SQL_FILE"
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
exec_psql_file "$DB_NAME" "$TABLE_SQL_FILE"
rm "$TABLE_SQL_FILE"

echo "✅ Installation complete! Sylon API and PostgreSQL are ready."
