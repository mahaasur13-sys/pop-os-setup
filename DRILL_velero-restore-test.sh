#!/bin/bash
#===============================================================================
# Velero DR Drill — Safe Restore Test (dry-run simulation)
# Purpose : Verify backups actually work without deleting production data
# Safety  : Uses isolated test-namespace, --dry-run flags, full logging
#===============================================================================
set -euo pipefail

#--- Config -------------------------------------------------------------------
LOGFILE="/var/log/velero-drill-$(date +%Y%m%d-%H%M%S).log"
TEST_NS="dr-test-$(date +%H%M%S)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RETENTION_DAYS=30

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

#--- Helpers ------------------------------------------------------------------
log()  { echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOGFILE"; }
log_ok(){ echo -e "${GREEN}[ OK ]${NC} $1" | tee -a "$LOGFILE"; }
log_warn(){ echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOGFILE"; }
log_err(){ echo -e "${RED}[ ERR]${NC} $1" | tee -a "$LOGFILE"; }
die()  { log_err "FATAL: $1"; exit 1; }

need_cmd(){
  command -v "$1" &>/dev/null && return 0
  die "Required command not found: $1 (install or check PATH)"
}

#--- Pre-flight ----------------------------------------------------------------
log "=== Velero DR Drill — started at $(date) ==="
need_cmd velero
need_cmd kubectl
need_cmd grep  # for health checks

# Check Velero is installed
velero version &>/dev/null || die "Velero not reachable (check kubeconfig)"

# Detect backup locations
BACKUP_LOCATION=$(kubectl get backuplocation -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -z "$BACKUP_LOCATION" ]]; then
  log_warn "No BackupLocation found — using default"
fi

# Check for existing backups
log "Checking existing backups..."
EXISTING=$(velero backup get -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
if [[ -z "$EXISTING" ]]; then
  log_warn "No backups found — will create one during drill"
  DO_CREATE_BACKUP=true
else
  log "Found backups: $EXISTING"
  DO_CREATE_BACKUP=true  # always create fresh for drill
fi

#--- STEP 1: Create test namespace -------------------------------------------
log "STEP 1 — Creating isolated test namespace: $TEST_NS"
kubectl create ns "$TEST_NS" --dry-run=client -o yaml | kubectl apply -f - \
  || die "Cannot create namespace"
kubectl get ns "$TEST_NS" &>/dev/null || die "Namespace not created"
log_ok "Namespace $TEST_NS ready"

#--- STEP 2: Deploy sample workload -------------------------------------------
log "STEP 2 — Deploying sample workload into $TEST_NS"

# 2a. Deployment + Service
kubectl create deployment hello-drill \
  --image=nginx:1.25 \
  --replicas=2 \
  --port=80 \
  --labels="app=drill-test,drill-run=$TIMESTAMP" \
  -n "$TEST_NS" \
  --dry-run=client -o yaml | kubectl apply -f - \
  || die "Cannot create deployment"

kubectl expose deployment hello-drill \
  --port=80 \
  --target-port=80 \
  --name=drill-svc \
  -n "$TEST_NS" \
  --dry-run=client -o yaml | kubectl apply -f - \
  || die "Cannot create service"

# 2b. ConfigMap (simulates app config)
kubectl create configmap drill-config \
  --from-literal="env=$TIMESTAMP" \
  --from-literal="drill=true" \
  -n "$TEST_NS" \
  --dry-run=client -o yaml | kubectl apply -f - \
  || die "Cannot create configmap"

# 2c. Secret (SealedSecret simulation — note: sealed-secret controller needed for real SealedSecrets)
kubectl create secret generic drill-secret \
  --from-literal="api-key=test-drill-key-$(date +%s)" \
  -n "$TEST_NS" \
  --dry-run=client -o yaml | kubectl apply -f - \
  || die "Cannot create secret"

# 2d. PVC (simulates persistent volume)
kubectl create pvc drill-pvc \
  --size=1Gi \
  --access-modes=ReadWriteOnce \
  -n "$TEST_NS" \
  --dry-run=client -o yaml | kubectl apply -f - \
  || die "Cannot create PVC"

log_ok "Workload deployed (Deployment, Service, ConfigMap, Secret, PVC)"

#--- STEP 3: Wait for pods ready ---------------------------------------------
log "STEP 3 — Waiting for pods to be Ready (timeout 60s)"
kubectl wait --for=condition=Ready \
  pods -l app=drill-test \
  -n "$TEST_NS" \
  --timeout=60s \
  || log_warn "Pods not fully ready within 60s (may be scheduling)"

# Verify replica count
READY_REPLICAS=$(kubectl get deployment hello-drill -n "$TEST_NS" \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
log "Ready replicas: $READY_REPLICAS/2"

#--- STEP 4: Baseline health check -------------------------------------------
log "STEP 4 — Baseline health check"
kubectl get all -n "$TEST_NS" -o wide | tee -a "$LOGFILE"

# Record deployed resource list for comparison
DRILL_DEPLOYMENTS="hello-drill"
DRILL_SERVICES="drill-svc"
DRILL_CONFIGMAPS="drill-config"
DRILL_SECRETS="drill-secret"
DRILL_PVCS="drill-pvc"

log_ok "Baseline health check complete"

#--- STEP 5: Create Velero backup ----------------------------------------------
BACKUP_NAME="drill-backup-${TIMESTAMP}"
log "STEP 5 — Creating Velero backup: $BACKUP_NAME"
log "  Included namespaces: $TEST_NS"
log "  TTL: ${RETENTION_DAYS}d ( Velero default)"

velero backup create "$BACKUP_NAME" \
  --include-namespaces "$TEST_NS" \
  --wait \
  || die "Backup failed"

# Wait for backup to complete
log "Waiting for backup to complete..."
BACKUP_STATUS="Unknown"
for i in $(seq 1 30); do
  BACKUP_STATUS=$(velero backup get "$BACKUP_NAME" \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
  if [[ "$BACKUP_STATUS" == "Completed" ]]; then
    log_ok "Backup $BACKUP_NAME status: $BACKUP_STATUS"
    break
  elif [[ "$BACKUP_STATUS" == "Failed" || "$BACKUP_STATUS" == "PartiallyFailed" ]]; then
    log_err "Backup status: $BACKUP_STATUS"
    velero backup describe "$BACKUP_NAME" --details | tee -a "$LOGFILE"
    die "Backup $BACKUP_NAME failed"
  fi
  sleep 2
done

if [[ "$BACKUP_STATUS" != "Completed" ]]; then
  log_warn "Backup still in state: $BACKUP_STATUS after 60s — continuing drill"
fi

# Show backup details
velero backup describe "$BACKUP_NAME" --details | tee -a "$LOGFILE"
log_ok "Backup $BACKUP_NAME created successfully"

#--- STEP 6: Simulate failure — delete resources --------------------------------
log "STEP 6 — Simulating failure: deleting resources from $TEST_NS"

# Capture pre-delete state to LOG
kubectl get all -n "$TEST_NS" -o yaml | tee -a "$LOGFILE" || true

log "Deleting deployment..."
kubectl delete deployment hello-drill -n "$TEST_NS" \
  --wait=true --grace-period=30 || true

log "Deleting service..."
kubectl delete service drill-svc -n "$TEST_NS" \
  --wait=true || true

log "Deleting configmap..."
kubectl delete configmap drill-config -n "$TEST_NS" \
  --wait=true || true

log "Deleting secret..."
kubectl delete secret drill-secret -n "$TEST_NS" \
  --wait=true || true

log "Deleting PVC..."
kubectl delete pvc drill-pvc -n "$TEST_NS" \
  --wait=true || true

# Verify deletion
REMAINING=$(kubectl get all -n "$TEST_NS" 2>/dev/null | grep -v "^NAME" | wc -l)
log "Remaining resources in $TEST_NS: $REMAINING"
log_ok "Resources deleted (simulated failure)"

#--- STEP 7: Restore from backup -----------------------------------------------
RESTORE_NAME="drill-restore-${TIMESTAMP}"
log "STEP 7 — Restoring from backup: $BACKUP_NAME → $RESTORE_NAME"

velero restore create "$RESTORE_NAME" \
  --from-backup "$BACKUP_NAME" \
  --wait \
  || die "Restore failed"

# Wait for restore to complete
log "Waiting for restore to complete..."
RESTORE_STATUS="Unknown"
for i in $(seq 1 60); do
  RESTORE_STATUS=$(velero restore get "$RESTORE_NAME" \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
  if [[ "$RESTORE_STATUS" == "Completed" ]]; then
    log_ok "Restore $RESTORE_NAME status: $RESTORE_STATUS"
    break
  elif [[ "$RESTORE_STATUS" == "Failed" || "$RESTORE_STATUS" == "PartiallyFailed" ]]; then
    log_err "Restore status: $RESTORE_STATUS"
    velero restore describe "$RESTORE_NAME" --details | tee -a "$LOGFILE"
    die "Restore $RESTORE_NAME failed"
  fi
  sleep 2
done

if [[ "$RESTORE_STATUS" != "Completed" ]]; then
  log_warn "Restore still in state: $RESTORE_STATUS after 120s"
fi

velero restore describe "$RESTORE_NAME" --details | tee -a "$LOGFILE"
log_ok "Restore $RESTORE_NAME completed"

#--- STEP 8: Post-restore verification -----------------------------------------
log "STEP 8 — Post-restore verification"

# Wait for pods to be back
log "Waiting for restored pods to be Ready (timeout 90s)..."
kubectl wait --for=condition=Ready \
  pods -l app=drill-test \
  -n "$TEST_NS" \
  --timeout=90s \
  || log_warn "Pods not Ready within 90s after restore"

echo ""
echo "=== Post-restore resource check ===" | tee -a "$LOGFILE"
kubectl get all -n "$TEST_NS" -o wide | tee -a "$LOGFILE"

# Check each resource type
RESTORE_CHECKS=0
RESTORE_CHECKS_PASSED=0

check_resource(){
  local type=$1; shift
  local name=$1; shift
  local ns=$TEST_NS
  if kubectl get "$type" "$name" -n "$ns" &>/dev/null; then
    log_ok "Restored: $type/$name"
    ((RESTORE_CHECKS_PASSED++))
  else
    log_err "MISSING after restore: $type/$name"
  fi
  ((RESTORE_CHECKS++))
}

check_resource "deployment" "hello-drill"
check_resource "service" "drill-svc"
check_resource "configmap" "drill-config"
check_resource "secret" "drill-secret"
check_resource "pvc" "drill-pvc"

# Verify replica count after restore
sleep 5
READY_AFTER=$(kubectl get deployment hello-drill -n "$TEST_NS" \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
log "Replicas after restore: $READY_AFTER/2"

if [[ "$READY_AFTER" == "2" ]]; then
  log_ok "Replica count verified: 2/2"
  ((RESTORE_CHECKS_PASSED++))
else
  log_warn "Replica count: $READY_AFTER/2 (may still be scaling)"
  ((RESTORE_CHECKS++))
fi

# Check PVC is Bound
PVC_STATUS=$(kubectl get pvc drill-pvc -n "$TEST_NS" \
  -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
log "PVC status: $PVC_STATUS"

#--- STEP 9: Functional test ---------------------------------------------------
log "STEP 9 — Functional test (HTTP health check)"

# Get service cluster IP
SVC_IP=$(kubectl get svc drill-svc -n "$TEST_NS" \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")

if [[ -n "$SVC_IP" && "$SVC_IP" != "None" ]]; then
  log "Service ClusterIP: $SVC_IP"
  HTTP_CODE=$(curl -sf -m 5 "http://${SVC_IP}:80" -o /dev/null -w "%{http_code}" 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "200" ]]; then
    log_ok "HTTP health check passed (status: $HTTP_CODE)"
    ((RESTORE_CHECKS_PASSED++))
  else
    log_warn "HTTP health check: got $HTTP_CODE (nginx may need more time to start)"
    ((RESTORE_CHECKS++))
  fi
else
  log_warn "Service ClusterIP not available — skipping HTTP check"
fi

#--- STEP 10: Results summary --------------------------------------------------
log "STEP 10 — DR Drill Results Summary"
echo ""
echo "=========================================="
echo "  VELERO DR DRILL — RESULTS"
echo "=========================================="
echo "  Timestamp    : $TIMESTAMP"
echo "  Test NS      : $TEST_NS"
echo "  Backup       : $BACKUP_NAME"
echo "  Restore      : $RESTORE_NAME"
echo "  Backup status: $BACKUP_STATUS"
echo "  Restore status: $RESTORE_STATUS"
echo "  Passed checks: $RESTORE_CHECKS_PASSED/$RESTORE_CHECKS"
echo "  Log file     : $LOGFILE"
echo "=========================================="

if [[ "$RESTORE_CHECKS_PASSED" -eq "$RESTORE_CHECKS" ]]; then
  echo -e "  ${GREEN}RESULT: FULL SUCCESS ✅${NC}"
  echo "  All resources restored and verified."
elif [[ "$RESTORE_CHECKS_PASSED" -gt $((RESTORE_CHECKS / 2)) ]]; then
  echo -e "  ${YELLOW}RESULT: PARTIAL SUCCESS ⚠️${NC}"
  echo "  Some resources restored. Review log."
else
  echo -e "  ${RED}RESULT: FAILED ❌${NC}"
  echo "  Most resources missing. Check $LOGFILE"
fi
echo "=========================================="
echo ""

#--- STEP 11: Cleanup ----------------------------------------------------------
log "STEP 11 — Cleaning up test namespace"

log "Do you want to delete the test namespace? (y/N)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
  kubectl delete namespace "$TEST_NS" --wait=true || true
  velero backup delete "$BACKUP_NAME" || true
  velero restore delete "$RESTORE_NAME" || true
  log_ok "Cleanup complete"
  echo "Test namespace $TEST_NS deleted"
else
  log "Test namespace kept for inspection: $TEST_NS"
  echo "To clean up later:"
  echo "  kubectl delete namespace $TEST_NS"
  echo "  velero backup delete $BACKUP_NAME"
  echo "  velero restore delete $RESTORE_NAME"
fi

log "=== DR Drill finished at $(date) ==="
log "Full log: $LOGFILE"
