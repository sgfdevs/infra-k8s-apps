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
replicas=migration.hack4goodsgf.com/replicas
url() {
  if [[ "$1" == hack4goodsgf-com-production ]]; then
    echo https://www.hack4goodsgf.com
  else
    echo https://staging.hack4goodsgf.com
  fi
}
application() { kubectl -n argocd get application "$1" -o json; }
check_app() {
  jq -e --arg ns "$1" --arg owner "$owner" --arg phase "$phase" --arg replicas "$replicas" '
    .spec.destination.namespace == $ns and .spec.destination.server == "https://kubernetes.default.svc" and
    .spec.syncPolicy.automated.selfHeal == true and .spec.syncPolicy.automated.enabled != false and
    .operation == null and .status.operationState.phase != "Running" and .status.operationState.phase != "Terminating" and
    .status.sync.status == "Synced" and .status.health.status == "Healthy" and
    (.metadata.annotations["argocd.argoproj.io/skip-reconcile"] // "") == "" and
    (.metadata.annotations[$owner] // "") == "" and (.metadata.annotations[$phase] // "") == "" and
    (.metadata.annotations[$replicas] // "") == ""
  ' >/dev/null || fail "$1 must be healthy, synced, idle, and free of previous migration state."
}
worker() {
  local ns=$1; shift
  kubectl -n "$ns" exec "$helper" -c wordpress -- bash /scripts/migration-wordpress.sh "$@"
}
mysql_worker() {
  local ns=$1; shift
  kubectl -n "$ns" exec "$helper" -c mysql -- bash /scripts/migration-mysql.sh "$@"
}
owned_app() {
  local app
  app=$(application "$1") || fail "Cannot read migration ownership for $1."
  jq -e --arg owner "$owner" --arg uid "$WORKFLOW_UID" '.metadata.annotations[$owner] == $uid' <<< "$app" >/dev/null
}
set_phase() {
  owned_app "$1" || fail "Migration no longer owns $1."
  kubectl -n argocd patch application "$1" --type=merge -p \
    "$(jq -n --arg phase "$phase" --arg value "$2" '{metadata:{annotations:{($phase):$value}}}')"
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
  local ns=$1 original canonical
  owned_app "$ns" || return 0
  original=$(application "$ns" | jq -er --arg key "$replicas" '.metadata.annotations[$key]')
  [[ "$original" == 1 ]] || fail "Invalid saved replica count for $ns."
  delete_helper "$ns"
  kubectl -n "$ns" scale deployment/hack4goodsgf --replicas="$original"
  canonical=$(url "$ns")
  if ! kubectl -n "$ns" rollout status deployment/hack4goodsgf --timeout=300s ||
     ! curl --fail --silent --show-error --retry 6 --retry-all-errors --retry-delay 5 \
       --retry-max-time 120 --connect-timeout 5 --max-time 30 \
       -H "Host: ${canonical#https://}" -H 'X-Forwarded-Proto: https' \
       "http://hack4goodsgf.$ns.svc.cluster.local/wp-login.php" -o /dev/null; then
    kubectl -n "$ns" scale deployment/hack4goodsgf --replicas=0
    echo "$ns failed its startup check and remains paused. Manual recovery is required." >&2
    return 1
  fi
  kubectl -n argocd patch application "$ns" --type=merge -p \
    "$(jq -n --arg owner "$owner" --arg phase "$phase" --arg replicas "$replicas" \
      '{metadata:{annotations:{($owner):null,($phase):null,($replicas):null,"argocd.argoproj.io/skip-reconcile":null}},spec:{syncPolicy:{automated:{selfHeal:true}}}}')"
}

if [[ "${1:-}" == cleanup ]]; then
  # Subshells retain errexit within resume, but allow cleanup of the other site too.
  set +e
  (set -e; resume "$source_ns")
  source_status=$?
  (
    set -e
    if owned_app "$target_ns"; then
      state=$(application "$target_ns" | jq -r --arg phase "$phase" '.metadata.annotations[$phase]')
      case "$state" in
        prepared|complete) resume "$target_ns" ;;
        *)
          delete_helper "$target_ns"
          echo "$target_ns remains stopped with Argo CD paused: the overwrite did not finish. No backup was taken. Recover the destination manually before clearing its migration annotations." >&2
          exit 1
          ;;
      esac
    fi
  )
  target_status=$?
  if [[ "$source_status" != 0 || "$target_status" != 0 ]]; then exit 1; fi
  exit 0
fi

[[ "$CONFIRMATION" == "OVERWRITE $destination FROM $source WITHOUT BACKUP" ]] ||
  fail "Confirmation must be: OVERWRITE $destination FROM $source WITHOUT BACKUP"
echo "Migrating $source to $destination. Destination users, passwords, database tables, and wp-content will be replaced. No backup will be taken."

for ns in "$source_ns" "$target_ns"; do
  application "$ns" | check_app "$ns"
  kubectl -n "$ns" get deployment hack4goodsgf -o json > "/work/$ns.json"
  jq -e '.spec.replicas == 1 and .status.observedGeneration == .metadata.generation and
    .status.updatedReplicas == 1 and .status.readyReplicas == 1 and .status.availableReplicas == 1' \
    "/work/$ns.json" >/dev/null || fail "$ns must have one fully rolled-out WordPress replica."
  [[ -z "$(kubectl -n "$ns" get pod "$helper" --ignore-not-found -o name)" ]] || fail "A migration helper already exists in $ns."
done
source_image=$(jq -r '.spec.template.spec.containers[] | select(.name=="wordpress") | .image' "/work/$source_ns.json")
target_image=$(jq -r '.spec.template.spec.containers[] | select(.name=="wordpress") | .image' "/work/$target_ns.json")
[[ "$source_image" == "$target_image" ]] || fail 'Align the staging and production WordPress image versions before migration.'

for ns in "$source_ns" "$target_ns"; do
  echo "Pausing $ns"
  # ResourceVersion rejects a concurrent change to the Application.
  app=$(application "$ns")
  check_app "$ns" <<< "$app"
  kubectl -n argocd patch application "$ns" --type=merge -p \
    "$(jq --arg owner "$owner" --arg uid "$WORKFLOW_UID" --arg phase "$phase" --arg replicas "$replicas" \
      '{metadata:{resourceVersion:.metadata.resourceVersion,annotations:{($owner):$uid,($phase):"prepared",($replicas):"1","argocd.argoproj.io/skip-reconcile":"true"}},spec:{syncPolicy:{automated:{selfHeal:false}}}}' <<< "$app")"
  kubectl -n "$ns" get deployment hack4goodsgf -o json | jq -S .spec > /work/current-spec.json
  diff /work/current-spec.json <(jq -S .spec "/work/$ns.json") || fail "$ns deployment changed during preflight."
  kubectl -n "$ns" scale deployment/hack4goodsgf --replicas=0 --current-replicas=1
  selector=$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' "/work/$ns.json")
  kubectl -n "$ns" wait pod -l "$selector" --for=delete --timeout=180s
  read_only=false
  if [[ "$ns" == "$source_ns" ]]; then read_only=true; fi
  # Clone the deployed image, credentials and security settings. The helper must
  # NOT carry the Deployment selector, or the ReplicaSet could adopt it.
  jq --arg ns "$ns" --arg uid "$WORKFLOW_UID" --arg helper "$helper" --argjson read_only "$read_only" '
    {apiVersion:"v1",kind:"Pod",metadata:{name:$helper,namespace:$ns,labels:{"migration.hack4goodsgf.com/workflow":$uid}},spec:.spec.template.spec}
    | del(.spec.initContainers)
    | .spec.restartPolicy="Never" | .spec.activeDeadlineSeconds=7200 | .spec.terminationGracePeriodSeconds=10
    | .spec.automountServiceAccountToken=false
    | .spec.volumes += [{name:"scripts",configMap:{name:"hack4goodsgf-migration-scripts",defaultMode:365}}]
    | (.spec.volumes[] | select(.name=="content") | .persistentVolumeClaim.readOnly)=$read_only
    | .spec.containers = [.spec.containers[] | select(.name=="wordpress")]
    | .spec.containers[0] |= (
        del(.ports,.livenessProbe,.startupProbe,.readinessProbe,.args)
        | .command=["bash","/scripts/migration-wordpress.sh","idle"]
        | .readinessProbe={exec:{command:["test","-f","/tmp/migration-ready"]},periodSeconds:2}
        | .resources.requests["ephemeral-storage"]="1Gi" | .resources.limits["ephemeral-storage"]="25Gi"
        | .volumeMounts += [{name:"scripts",mountPath:"/scripts",readOnly:true}]
        | (.volumeMounts[] | select(.name=="content") | .readOnly)=$read_only)
    | .spec.containers += [{
        name:"mysql",image:"mysql:8.4@sha256:43bd9764df60666fb2ba2cf8217dd17b3d2414c150005d2fdd07a0cd73d3b7f5",
        command:["sleep","7200"],env:[.spec.containers[0].env[] | select(.name | startswith("WORDPRESS_DB_"))],
        securityContext:{runAsUser:33,runAsGroup:33,runAsNonRoot:true,readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},
        resources:{requests:{cpu:"100m",memory:"64Mi"},limits:{cpu:"500m",memory:"256Mi"}},
        volumeMounts:[{name:"scripts",mountPath:"/scripts",readOnly:true},{name:"tmp",mountPath:"/tmp"}]
      }]
  ' "/work/$ns.json" | kubectl -n "$ns" create -f -
  kubectl -n "$ns" wait "pod/$helper" --for=condition=Ready --timeout=300s
  mysql_worker "$ns" check
  worker "$ns" check "$(url "$ns")"
done

[[ "$(worker "$source_ns" prefix)" == "$(worker "$target_ns" prefix)" ]] || fail 'WordPress table prefixes must match.'
worker "$source_ns" urls > /work/source-urls.txt
mysql_worker "$source_ns" export | gzip > /work/database.sql.gz
kubectl -n "$source_ns" exec "$helper" -c wordpress -- tar -C /var/www/html/wp-content -czf - . > /work/content.tar.gz
gzip -t /work/database.sql.gz /work/content.tar.gz
kubectl -n "$target_ns" exec -i "$helper" -c wordpress -- bash /scripts/migration-wordpress.sh stage-content < /work/content.tar.gz
# The source snapshot is complete. Release its volume and reopen the source now.
resume "$source_ns"

echo "Replacing $target_ns data"
set_phase "$target_ns" importing
gzip -dc /work/database.sql.gz | kubectl -n "$target_ns" exec -i "$helper" -c mysql -- bash /scripts/migration-mysql.sh import
worker "$target_ns" replace-content
kubectl -n "$target_ns" exec -i "$helper" -c wordpress -- bash /scripts/migration-wordpress.sh normalize < /work/source-urls.txt
set_phase "$target_ns" complete
echo 'Data copy and URL checks succeeded. The exit handler will restart and check the destination.'
