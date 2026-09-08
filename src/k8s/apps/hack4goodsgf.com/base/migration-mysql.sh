#!/bin/bash
set -euo pipefail

export MYSQL_PWD="$WORDPRESS_DB_PASSWORD"
host=${WORDPRESS_DB_HOST%:*}
port=${WORDPRESS_DB_HOST##*:}
if [[ "$host" == "$port" ]]; then port=3306; fi
connection=(--host="$host" --port="$port" --user="$WORDPRESS_DB_USER")
mysql_db() {
  mysql "${connection[@]}" --database="$WORDPRESS_DB_NAME" --batch --skip-column-names "$@"
}

case "${1:-}" in
  check)
    # Do not silently omit SQL objects or import source-account DEFINER clauses.
    unsupported=$(mysql_db -e '
      SELECT
        (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type<>"BASE TABLE") +
        (SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()) +
        (SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema=DATABASE()) +
        (SELECT COUNT(*) FROM information_schema.events WHERE event_schema=DATABASE());')
    if [[ "$unsupported" != 0 ]]; then
      echo 'Migration requires a table-only WordPress database; views, triggers, routines, or events need separate handling.' >&2
      exit 1
    fi
    ;;
  export)
    mysqldump "${connection[@]}" --single-transaction --no-tablespaces \
      --set-gtid-purged=OFF --column-statistics=0 --skip-add-locks \
      --hex-blob --default-character-set=utf8mb4 "$WORDPRESS_DB_NAME"
    ;;
  import)
    # Remove destination-only tables too, without dropping the operator-managed DB.
    # shellcheck disable=SC2016 # SQL identifier quoting, not shell substitution.
    drops=$(mysql_db -e 'SELECT CONCAT("DROP TABLE IF EXISTS `", REPLACE(table_name,"`","``"), "`;") FROM information_schema.tables WHERE table_schema=DATABASE();')
    printf 'SET FOREIGN_KEY_CHECKS=0;\n%s\n' "$drops" | mysql_db
    mysql_db
    ;;
  *) echo 'Expected check, export, or import' >&2; exit 1 ;;
esac
