#!/bin/sh
set -eu
# Only hostname/port tokens are accepted; no credentials or Squid directives.
validate_host() {
  case "$1" in *[!a-zA-Z0-9._-]*|-*|.*) echo 'Invalid egress upstream host' >&2; exit 1;; esac
}
validate_port() {
  case "$1" in ''|*[!0-9]*) echo 'Invalid egress upstream port' >&2; exit 1;; esac
  [ "$1" -gt 0 ] && [ "$1" -le 65535 ] || exit 1
}
# Squid's peer connector can select an AAAA record even when the container
# lacks IPv6 routing. Prefer a configured upstream's IPv4 address; retain the
# hostname for IPv6-only deployments. Client destination ACLs remain unchanged.
peer_host() {
  ipv4=$(getent ahostsv4 "$1" 2>/dev/null | awk 'NR == 1 { print $1; exit }')
  printf '%s' "${ipv4:-$1}"
}
cn_host=${EGRESS_CN_UPSTREAM_HOST:-}
cn_port=${EGRESS_CN_UPSTREAM_PORT:-7897}
global_host=${EGRESS_GLOBAL_UPSTREAM_HOST:-${EGRESS_FALLBACK_UPSTREAM_HOST:-host.docker.internal}}
global_port=${EGRESS_GLOBAL_UPSTREAM_PORT:-7898}
[ -n "${EGRESS_GLOBAL_UPSTREAM_HOST:-}" ] || global_port=${EGRESS_FALLBACK_UPSTREAM_PORT:-7897}
validate_host "$cn_host"
validate_host "$global_host"
[ -n "$global_host" ] || exit 1
validate_port "$cn_port"
validate_port "$global_port"
{
  echo 'acl cn_residential myportname cn_residential'
  echo 'acl global_residential myportname global_residential'
  if [ -n "$cn_host" ]; then
    cn_peer=$(peer_host "$cn_host")
    echo "cache_peer $cn_peer parent $cn_port 0 no-query default name=cn_parent"
    echo 'cache_peer_access cn_parent allow cn_residential'
    echo 'cache_peer_access cn_parent deny all'
    echo 'never_direct allow cn_residential'
  else
    # An existing domestic ISP connection needs no additional proxy node.
    echo 'always_direct allow cn_residential'
  fi
  global_peer=$(peer_host "$global_host")
  echo "cache_peer $global_peer parent $global_port 0 no-query default name=global_parent"
  echo 'cache_peer_access global_parent allow global_residential'
  echo 'cache_peer_access global_parent deny all'
  echo 'never_direct allow global_residential'
} > /tmp/egress-routes.conf
squid -k parse -f /etc/squid/policy/squid.conf
exec squid -N -f /etc/squid/policy/squid.conf
