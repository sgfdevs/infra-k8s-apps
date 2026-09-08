#!/bin/bash
# PHP variables in single-quoted snippets must reach PHP without shell expansion.
# shellcheck disable=SC2016
set -euo pipefail
cd /var/www/html
wp_safe() { wp --skip-plugins --skip-themes "$@"; }
replace_url() {
  local old=${1%/}
  [[ -n "$old" && "$old" != "$WORDPRESS_HOME" ]] || return 0
  case "$old" in http://*|https://*) ;; *) echo 'Invalid source URL' >&2; exit 1 ;; esac
  wp_safe search-replace "$old" "$WORDPRESS_HOME" \
    --all-tables --precise --skip-columns=guid --report-changed-only
  # Plugins also store JSON with escaped slashes, sometimes inside PHP serialization.
  wp_safe search-replace "${old//\//\\/}" "${WORDPRESS_HOME//\//\\/}" \
    --all-tables --precise --skip-columns=guid --report-changed-only
}
flush_valkey() {
  php -r '
    $redis = new Redis();
    $redis->connect("hack4goodsgf-valkey", 6379);
    $redis->auth(getenv("WORDPRESS_REDIS_PASSWORD"));
    if (!$redis->flushDB()) { throw new RuntimeException("Valkey flush failed"); }
  '
}

case "${1:-}" in
  idle)
    # Core and wp-config.php belong to this helper, not the copied content volume.
    find /usr/src/wordpress -mindepth 1 -maxdepth 1 ! -name wp-content \
      -exec cp -R -t /var/www/html {} +
    printf '%s\n' "$WORDPRESS_CONFIG_EXTRA" | wp config create \
      --dbname="$WORDPRESS_DB_NAME" --dbuser="$WORDPRESS_DB_USER" \
      --dbpass="$WORDPRESS_DB_PASSWORD" --dbhost="$WORDPRESS_DB_HOST" \
      --dbprefix="${WORDPRESS_TABLE_PREFIX:-wp_}" \
      --skip-check --skip-salts --extra-php --force
    touch /tmp/migration-ready
    exec sleep 7200
    ;;
  check)
    [[ "$WORDPRESS_HOME" == "$2" && "$WORDPRESS_SITEURL" == "$2" ]]
    wp_safe core is-installed
    ;;
  prefix)
    printf '%s\n' "${WORDPRESS_TABLE_PREFIX:-wp_}"
    ;;
  urls)
    # Read stored values, not the WP_HOME/WP_SITEURL constant overrides.
    wp_safe eval 'global $wpdb; foreach (["home", "siteurl"] as $name) {
      echo $wpdb->get_var($wpdb->prepare("SELECT option_value FROM $wpdb->options WHERE option_name = %s", $name)), "\n";
    }'
    ;;
  stage-content)
    mkdir -m 700 /tmp/migration-content
    tar --extract --gzip --file=- --directory=/tmp/migration-content --no-same-owner --same-permissions
    test -d /tmp/migration-content/plugins
    test -d /tmp/migration-content/themes
    ;;
  replace-content)
    test -d /tmp/migration-content/plugins
    test -d /tmp/migration-content/themes
    find wp-content -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    find /tmp/migration-content -mindepth 1 -maxdepth 1 -exec mv -t wp-content -- {} +
    rmdir /tmp/migration-content
    ;;
  normalize)
    # An imported options table must not be shadowed by the destination's old cache.
    flush_valkey
    while IFS= read -r old; do
      replace_url "$old"
    done
    # Jason's aliases, including HTTP www and the reverse production-to-staging case.
    for host in hack4goodsgf.com www.hack4goodsgf.com staging.hack4goodsgf.com; do
      for scheme in http https; do
        replace_url "$scheme://$host"
      done
    done
    wp_safe transient delete --all
    # Regenerate rules on the next web request, with all plugins and the theme loaded.
    wp_safe eval 'delete_option("rewrite_rules");'
    if [[ -d wp-content/cache && ! -L wp-content/cache ]]; then
      find wp-content/cache -mindepth 1 -maxdepth 1 ! -name .htaccess ! -name index.php -exec rm -rf -- {} +
    fi
    flush_valkey
    wp_safe core is-installed
    wp_safe eval 'global $wpdb; foreach (["home" => "WORDPRESS_HOME", "siteurl" => "WORDPRESS_SITEURL"] as $name => $env) {
      $stored = $wpdb->get_var($wpdb->prepare("SELECT option_value FROM $wpdb->options WHERE option_name = %s", $name));
      if ($stored !== getenv($env)) { WP_CLI::error("Stored URL does not match destination configuration"); }
    }'
    ;;
  *) echo 'Unknown WordPress migration operation' >&2; exit 1 ;;
esac
