#!/bin/sh
# Runs as root for exactly one reason: a Railway volume mounts at runtime, shadows whatever the
# image had at that path, and arrives owned by root:root. The app runs as uid 10001, so without
# this it cannot write its own logs — and logging handlers swallow I/O errors, so the symptom
# would be an empty log directory rather than a crash.
#
# Fix the ownership, then drop privileges immediately. Nothing after the exec runs as root.
set -eu

LOG_DIR="${LOG_DIR:-/data/logs}"
APP_UID=10001
APP_GID=10001

mkdir -p "$LOG_DIR"
chown -R "$APP_UID:$APP_GID" "$LOG_DIR"

# Prove the drop worked and the target is writable, in the deploy log, before serving traffic.
echo "entrypoint: LOG_DIR=$LOG_DIR owner=$(stat -c '%u:%g' "$LOG_DIR") dropping to $APP_UID"

exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups \
    uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
