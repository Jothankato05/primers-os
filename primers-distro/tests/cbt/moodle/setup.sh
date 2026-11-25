#!/bin/bash
# A real, self-hosted Moodle for the CBT compatibility VM test (exam-moodle):
# PostgreSQL, Moodle MOODLE_TAG installed from its CLI, a course with a quiz
# and a student, served on 127.0.0.1:8780 as http://moodle.primers.test:8780
# (the VM reaches it through QEMU at 10.0.2.2:8780).
#   setup.sh WORKDIR        (as root; needs PHP 8.1+ and PostgreSQL 13+)
# Prints the quiz's course-module id as "CMID=<n>" on its last line.
set -euo pipefail
work=${1:?usage: setup.sh WORKDIR}
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tag=${MOODLE_TAG:-v4.5.16}
url=${MOODLE_URL:-http://moodle.primers.test:8780}
port=${MOODLE_PORT:-8780}
# Test-only credentials for a throwaway local server
dbpass=moodle-test admin_pass=Admin-Test-1

mkdir -p "$work"
cd "$work"
if [ ! -d moodle ]; then
  git clone -q --depth 1 --branch "$tag" https://github.com/moodle/moodle.git moodle
fi
mkdir -p moodledata
chown -R www-data:www-data moodledata 2> /dev/null || true
chmod 0777 moodledata

sudo -u postgres psql -qtc "SELECT 1 FROM pg_roles WHERE rolname='moodle'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE USER moodle WITH PASSWORD '$dbpass'"
sudo -u postgres psql -qtc "SELECT 1 FROM pg_database WHERE datname='moodle'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE DATABASE moodle OWNER moodle ENCODING 'UTF8' TEMPLATE template0"

php=(php -d max_input_vars=5000 -d memory_limit=512M)
if [ ! -f moodle/config.php ]; then
  "${php[@]}" moodle/admin/cli/install.php --non-interactive --agree-license --lang=en \
    --wwwroot="$url" --dataroot="$work/moodledata" --dbtype=pgsql --dbhost=127.0.0.1 \
    --dbname=moodle --dbuser=moodle --dbpass="$dbpass" --fullname="PRIMERS CBT test" \
    --shortname=primers-cbt --adminuser=admin --adminpass="$admin_pass" --adminemail=admin@primers.test \
    --supportemail=admin@primers.test > install.log 2>&1 || { tail -30 install.log; exit 1; }
fi
cmid=$("${php[@]}" "$here/make_quiz.php" "$work/moodle")

# Serve it: PHP's own web server, a few workers
pkill -f "[p]hp .*-S 127.0.0.1:$port" 2> /dev/null || true
# Fully detached (its own session, no terminal or pipe of ours)
(cd moodle && PHP_CLI_SERVER_WORKERS=4 setsid -f "${php[@]}" -S "127.0.0.1:$port" > "$work/server.log" 2>&1 < /dev/null)
for _ in $(seq 1 30); do
  curl -s -o /dev/null -H "Host: ${url#http://}" "http://127.0.0.1:$port/login/index.php" && break
  sleep 1
done
echo "CMID=$cmid"
