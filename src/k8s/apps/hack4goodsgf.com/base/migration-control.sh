#!/bin/bash
set -euo pipefail

fail() { echo "$*" >&2; exit 1; }
case "$DIRECTION" in
  staging-to-production) source=staging; destination=production ;;
  production-to-staging) source=production; destination=staging ;;
  *) fail 'Select staging-to-production or production-to-staging.' ;;
esac
source_ns="hack4goodsgf-com-$source"
target_ns="hack4goodsgf-com-$destination"
[[ "$WORKFLOW_NAMESPACE" == "$target_ns" ]] || fail "Submit this workflow in $target_ns, the destination namespace."
helper=hack4goodsgf-migration
owner=migration.hack4goodsgf.com/workflow
phase=migration.hack4goodsgf.com/phase
url() {
  if [[ "$1" == hack4goodsgf-com-production ]]; then echo https://www.hack4goodsgf.com;
  else echo https://staging.hack4goodsgf.com; fi
}
application() { kubectl -n argocd get application "$1" -o json; }
check_app() {
  jq -e --arg ns "$1" --arg owner "$owner" --arg phase "$phase" '
    .spec.destination.namespace == $ns and .spec.destination.server == "https://kubernetes.default.svc" and
    .spec.syncPolicy.automated.selfHeal == true and .spec.syncPolicy.automated.enabled != false and
    .operation == null and .status.operationState.phase != "Running" and .status.operationState.phase != "Terminating" and
    .status.sync.status == "Synced" and .status.health.status == "Healthy" and
    (.metadata.annotations["argocd.argoproj.io/skip-reconcile"] // "") == "" and
    (.metadata.annotations[$owner] // "") == "" and (.metadata.annotations[$phase] // "") == ""
  ' >/dev/null || fail "$1 must be healthy, synced, idle, and free of previous migration state."
}
worker() {
  local ns=$1 container=$2; shift 2
  kubectl -n "$ns" exec "$helper" -c "$container" -- bash "/scripts/migration-$container.sh" "$@"
}
owned_app() {
  local app
  app=$(application "$1") || fail "Cannot read migration ownership for $1."
  jq -e --arg owner "$owner" --arg uid "$WORKFLOW_UID" '.metadata.annotations[$owner] == $uid' <<< "$app" >/dev/null
}
set_phase() {
  # Test ownership and change phase in the same API request.
  kubectl -n argocd patch application "$target_ns" --type=json -p \
    "$(jq -n --arg uid "$WORKFLOW_UID" --arg value "$1" '[
      {op:"test",path:"/metadata/annotations/migration.hack4goodsgf.com~1workflow",value:$uid},
      {op:"replace",path:"/metadata/annotations/migration.hack4goodsgf.com~1phase",value:$value}]')"
}
delete_helper() {
  local pod
  pod=$(kubectl -n "$1" get pod "$helper" --ignore-not-found -o json)
  if [[ -n "$pod" ]]; then
    jq -e --arg uid "$WORKFLOW_UID" '.metadata.labels["migration.hack4goodsgf.com/workflow"] == $uid' <<< "$pod" >/dev/null ||
      fail "$1/$helper belongs to another operation; manual cleanup is required."
    kubectl -n "$1" delete pod "$helper" --wait=true --timeout=180s
  fi
}
resume() {
  local ns=$1 canonical
  owned_app "$ns" || return 0
  delete_helper "$ns"
  kubectl -n "$ns" scale deployment/hack4goodsgf --replicas=1
  canonical=$(url "$ns")
  if ! kubectl -n "$ns" rollout status deployment/hack4goodsgf --timeout=300s ||
     ! curl --fail --silent --show-error --retry 6 --retry-all-errors --retry-delay 5 \
       --retry-max-time 120 --connect-timeout 5 --max-time 30 \
       -H "Host: ${canonical#https://}" -H 'X-Forwarded-Proto: https' \
       "http://hack4goodsgf.$ns.svc.cluster.local/wp-login.php" -o /dev/null; then
    kubectl -n "$ns" scale deployment/hack4goodsgf --replicas=0
    fail "$ns failed its startup check and remains paused. Manual recovery is required."
  fi
  kubectl -n argocd patch application "$ns" --type=merge -p \
    "$(jq -n --arg owner "$owner" --arg phase "$phase" \
      '{metadata:{annotations:{($owner):null,($phase):null,"argocd.argoproj.io/skip-reconcile":null}},spec:{syncPolicy:{automated:{selfHeal:true}}}}')"
}

case "${1:-}" in
  preflight)
    [[ "$CONFIRMATION" == "OVERWRITE $destination FROM $source WITHOUT BACKUP" ]] ||
      fail "Confirmation must be: OVERWRITE $destination FROM $source WITHOUT BACKUP"
    for ns in "$source_ns" "$target_ns"; do
      application "$ns" | check_app "$ns"
      [[ -z "$(kubectl -n "$ns" get pod "$helper" --ignore-not-found -o name)" ]] || fail "A helper already exists in $ns."
      kubectl -n "$ns" get deployment hack4goodsgf -o json > "/tmp/$ns.json"
      jq -e '.spec.replicas == 1 and .status.observedGeneration == .metadata.generation and
        .status.updatedReplicas == 1 and .status.readyReplicas == 1 and .status.availableReplicas == 1' \
        "/tmp/$ns.json" >/dev/null || fail "$ns must have one fully rolled-out WordPress replica."
      jq -r '.spec.template.spec.containers[] | select(.name=="wordpress") | .image' "/tmp/$ns.json" > "/tmp/$ns-image"
    done
    cmp "/tmp/$source_ns-image" "/tmp/$target_ns-image" || fail 'Align the WordPress image versions before migration.'
    cp "/tmp/$source_ns-image" /tmp/image
    printf '%s' "$source_ns" > /tmp/source-namespace
    ;;
  pause)
    for ns in "$source_ns" "$target_ns"; do
      app=$(application "$ns")
      check_app "$ns" <<< "$app"
      kubectl -n argocd patch application "$ns" --type=merge -p \
        "$(jq --arg owner "$owner" --arg uid "$WORKFLOW_UID" --arg phase "$phase" \
          '{metadata:{resourceVersion:.metadata.resourceVersion,annotations:{($owner):$uid,($phase):"prepared","argocd.argoproj.io/skip-reconcile":"true"}},spec:{syncPolicy:{automated:{selfHeal:false}}}}' <<< "$app")"
      image=$(kubectl -n "$ns" get deployment hack4goodsgf -o jsonpath='{.spec.template.spec.containers[?(@.name=="wordpress")].image}')
      [[ "$image" == "$2" ]] || fail "$ns image changed during preflight."
      kubectl -n "$ns" scale deployment/hack4goodsgf --replicas=0 --current-replicas=1
      kubectl -n "$ns" wait pod -l app.kubernetes.io/name=hack4goodsgf --for=delete --timeout=180s
    done
    ;;
  export)
    for ns in "$source_ns" "$target_ns"; do
      kubectl -n "$ns" wait "pod/$helper" --for=condition=Ready --timeout=300s
      worker "$ns" mysql check
      worker "$ns" wordpress check "$(url "$ns")"
    done
    [[ "$(worker "$source_ns" wordpress prefix)" == "$(worker "$target_ns" wordpress prefix)" ]] || fail 'WordPress table prefixes must match.'
    # Keep transfer files in the destination helper, not in a separate workflow PVC.
    worker "$source_ns" wordpress urls | kubectl -n "$target_ns" exec -i "$helper" -c wordpress -- bash -ec 'cat > /tmp/source-urls.txt'
    worker "$source_ns" mysql export | kubectl -n "$target_ns" exec -i "$helper" -c mysql -- bash -ec 'cat > /tmp/database.sql; test -s /tmp/database.sql'
    kubectl -n "$source_ns" exec "$helper" -c wordpress -- tar -C /var/www/html/wp-content -czf - . |
      kubectl -n "$target_ns" exec -i "$helper" -c wordpress -- bash /scripts/migration-wordpress.sh stage-content
    ;;
  import)
    set_phase importing
    worker "$target_ns" mysql import
    worker "$target_ns" wordpress replace-content
    ;;
  normalize)
    worker "$target_ns" wordpress normalize
    set_phase complete
    ;;
  resume-source) resume "$source_ns" ;;
  resume-destination)
    owned_app "$target_ns" || exit 0
    state=$(application "$target_ns" | jq -r --arg phase "$phase" '.metadata.annotations[$phase]')
    case "$state" in
      prepared|complete) resume "$target_ns" ;;
      *)
        delete_helper "$target_ns"
        fail "$target_ns remains stopped and Argo-paused: the overwrite did not finish. No backup was taken. Manual recovery is required."
        ;;
    esac
    ;;
  *) fail 'Unknown migration step.' ;;
esac
