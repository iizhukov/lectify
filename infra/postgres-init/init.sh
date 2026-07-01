#!/bin/bash

set -e

for f in /docker-entrypoint-initdb.d/services/*.sql; do
    [ -e "$f" ] || continue
    basename "$f" .sql | tr '[:upper:]' '[:lower:]' | xargs -I{} psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname {} -f "$f"
done
