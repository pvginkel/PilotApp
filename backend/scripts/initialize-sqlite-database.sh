#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

print_usage() {
    cat <<'EOF'
Usage: initialize-sqlite-database.sh --db PATH [--load-test-data]

Options:
  --db PATH            Path to the SQLite database file to initialize (required)
  --load-test-data     Load fixed test dataset after initializing the schema
  -h, --help           Show this help message
EOF
}

DB_PATH=""
LOAD_TEST_DATA=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --db requires a value." >&2
                print_usage
                exit 1
            fi
            DB_PATH="$2"
            shift 2
            ;;
        --load-test-data)
            LOAD_TEST_DATA=true
            shift
            ;;
        --help|-h)
            print_usage
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1" >&2
            print_usage
            exit 1
            ;;
    esac
done

if [[ -z "$DB_PATH" ]]; then
    echo "Error: --db PATH is required." >&2
    print_usage
    exit 1
fi

export DATABASE_URL="sqlite:////${DB_PATH}"

echo "Initializing SQLite database at $DB_PATH"
echo "Using DATABASE_URL=$DATABASE_URL"

cd "$BACKEND_DIR"

if $LOAD_TEST_DATA; then
    echo "Loading fixed test dataset into SQLite database..."
    poetry run cli load-test-data --yes-i-am-sure
else
    echo "Applying database migrations..."
    poetry run cli upgrade-db
fi

echo "SQLite database initialization complete."
