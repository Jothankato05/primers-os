#!/bin/bash
# A real, self-hosted TCExam for the CBT compatibility VM test (exam-tcexam):
# PostgreSQL, TCExam TCEXAM_TAG installed with its own CLI installer, a test
# with two questions open to a student, served on 127.0.0.1:8781 as
# http://tcexam.primers.test:8781 (the VM reaches it at 10.0.2.2:8781).
#   setup.sh WORKDIR        (as root; needs PHP 8.2+, Composer, PostgreSQL)
# Prints the test's id as "TESTID=<n>" on its last line.
set -euo pipefail
work=${1:?usage: setup.sh WORKDIR}
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tag=${TCEXAM_TAG:-17.6.0}
port=${TCEXAM_PORT:-8781}
host=tcexam.primers.test
dbpass=tcexam-test          # a throwaway local test server

mkdir -p "$work"
cd "$work"
if [ ! -d tcexam ]; then
  git clone -q --depth 1 --branch "$tag" https://github.com/tecnickcom/tcexam.git tcexam
fi
# PDF font building (post-install script) isn't needed for taking a test
(cd tcexam && composer install --no-dev --no-interaction --quiet --no-scripts)

sudo -u postgres psql -qtc "SELECT 1 FROM pg_roles WHERE rolname='tcexam'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE USER tcexam WITH PASSWORD '$dbpass'"
if ! sudo -u postgres psql -qtc "SELECT 1 FROM pg_database WHERE datname='tcexam'" | grep -q 1; then
  sudo -u postgres psql -qc "CREATE DATABASE tcexam OWNER tcexam ENCODING 'UTF8' TEMPLATE template0"
  TCEXAM_DB_TYPE=POSTGRESQL TCEXAM_DB_HOST=127.0.0.1 TCEXAM_DB_PORT=5432 TCEXAM_DB_NAME=tcexam \
    TCEXAM_DB_USER=tcexam TCEXAM_DB_PASSWORD="$dbpass" TCEXAM_DB_CREATE=0 \
    TCEXAM_PATH_HOST="http://$host:$port" TCEXAM_PATH_TCEXAM=/ TCEXAM_STANDARD_PORT="$port" \
    php tcexam/install/install_cli.php
fi
# Served over plain http, as many campus LAN installs are: TCExam marks its
# cookies Secure by default, which browsers drop on http (sign-in loops).
sed -i "s/define('K_COOKIE_SECURE', true);/define('K_COOKIE_SECURE', false);/" tcexam/shared/config/tce_config.php
grep -q "define('K_COOKIE_SECURE', false);" tcexam/shared/config/tce_config.php
testid=$(php "$here/make_test.php" "$dbpass")

pkill -f "[p]hp .*-S 127.0.0.1:$port" 2> /dev/null || true
# Fully detached (its own session, no terminal or pipe of ours)
(cd tcexam && PHP_CLI_SERVER_WORKERS=4 setsid -f php -S "127.0.0.1:$port" > "$work/tcexam-server.log" 2>&1 < /dev/null)
for _ in $(seq 1 30); do
  curl -s -o /dev/null -H "Host: $host:$port" "http://127.0.0.1:$port/public/code/index.php" && break
  sleep 1
done
echo "TESTID=$testid"
