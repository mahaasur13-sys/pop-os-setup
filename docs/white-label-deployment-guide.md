# ROMA Platform — White-Label Deployment Guide

> **Version:** 1.0.0 | **Target:** Pop!_OS 24.04 + k3s + ROMA Execution Bridge v1.0.0  
> **Audience:** Partners deploying branded compute economy platforms

---

## Navigation

- [Prerequisites](#prerequisites)
- [Step 1 — OS Setup](#step-1--os-setup)
- [Step 2 — Cluster Profile](#step-2--cluster-profile)
- [Step 3 — ROMA Installation](#step-3--roma-installation)
- [Step 4 — Tenant Provisioning](#step-4--tenant-provisioning)
- [Step 5 — Branding](#step-5--branding)
- [Step 6 — Domain + TLS](#step-6--domain--tls)
- [Step 7 — Stripe Payments](#step-7--stripe-payments)
- [Step 8 — Verification](#step-8--verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Value |
|-------------|-------|
| OS | Pop!_OS 24.04 LTS (NVIDIA ISO) |
| CPU | 8+ cores (16 for AI workloads) |
| RAM | 32 GB minimum |
| GPU | NVIDIA GPU with CUDA support (optional for CPU-only) |
| Disk | 500 GB+ NVMe |
| Network | Static IP, ports 443/80 open |

---

## Step 1 — OS Setup

### 1.1 Boot Pop!_OS NVIDIA Edition from USB

Download from [pop.plan-k.org](https://pop.plan-k.org) → NVIDIA ISO.

### 1.2 Run Auto-Setup Script

```bash
# Full profile (all 26 stages):
sudo bash pop-os-setup-v5.sh

# Cluster profile (k3s + storage):
sudo PROFILE=cluster bash pop-os-setup-v5.sh

# AI Dev profile (dev + AI + GPU, no storage):
sudo PROFILE=ai-dev bash pop-os-setup-v5.sh
```

### 1.3 Verify GPU Acceleration

```bash
nvidia-smi
# Expected: GPU table with driver version, CUDA version, memory usage

system76-power graphics nvidia  # performance mode
```

---

## Step 2 — Cluster Profile

Choose based on use case:

| Profile | Stages | Use Case |
|---------|--------|----------|
| `workstation` | 1-3, 7-15, 18 | Single-node dev/AI (no k8s) |
| `cluster` | 1-3, 6-8, 14, 16-20 | Multi-node k3s + storage |
| `ai-dev` | 1-15, 18 | Dev + AI + GPU (no storage) |
| `full` | 1-26 | Everything |

**Recommended for partners:** `PROFILE=cluster` (includes k3s, storage, monitoring).

### Multi-Node Setup (cluster profile)

On **server node**:

```bash
sudo K3S_ROLE=server TAILSCALE_AUTHKEY=tskey-auth-xxxx bash pop-os-setup-v5.sh
```

On **agent nodes**:

```bash
# Get join token from server:
sudo cat /var/lib/k3s/join-token-$(hostname).txt

# Then on agent:
sudo K3S_ROLE=agent K3S_TOKEN=<token> K3S_SERVER_IP=<server-tailscale-ip> \
  TAILSCALE_AUTHKEY=tskey-auth-xxxx bash pop-os-setup-v5.sh
```

---

## Step 3 — ROMA Installation

### 3.1 Install Helm Chart

```bash
# Add ROMA Helm repo (or use local tarball from release-artifacts/):
helm repo add roma https://ghcr.io/mahaasur13-sys/charts
helm repo update

# Install with release name "roma":
helm install roma oci://ghcr.io/mahaasur13-sys/charts/roma-execution-bridge \
  --version 1.0.0 \
  -n roma-system \
  --create-namespace

# Or from local tarball:
helm install roma ./release-artifacts/roma-execution-bridge-1.0.0.tgz \
  -n roma-system \
  --create-namespace
```

### 3.2 Verify Installation

```bash
kubectl get pods -n roma-system
# Expected: all pods Running

kubectl get crd | grep roma
# Expected: romatenants.roma.io

helm list -n roma-system
# Expected: roma-1.0.0
```

### 3.3 Expose Services

```bash
# Port-forward for local access (testing):
kubectl port-forward -n roma-system svc/roma-kong-kong-proxy 8000:80 &
kubectl port-forward -n roma-system svc/roma-minio-console 9001:9001 &

# Or via Tailscale Funnel (public):
sudo tailscale funnel 443
sudo tailscale serve https+insecure://localhost:8000
```

---

## Step 4 — Tenant Provisioning

ROMA uses `RomaTenant` CRD for multi-tenant provisioning.

### 4.1 Free Tier Tenant

```bash
cat << 'EOF' | kubectl apply -f -
apiVersion: roma.io/v1
kind: RomaTenant
metadata:
  name: tenant-free-demo
  namespace: roma-system
spec:
  tier: free
  plan:
    cpu_limit: "2"
    memory_limit: 4Gi
    gpu_limit: "0"
    storage_quota: 10Gi
    priority: low
  billing:
    enabled: false
EOF
```

### 4.2 Pro Tier Tenant

```bash
cat << 'EOF' | kubectl apply -f -
apiVersion: roma.io/v1
kind: RomaTenant
metadata:
  name: tenant-pro-demo
  namespace: roma-system
spec:
  tier: pro
  plan:
    cpu_limit: "8"
    memory_limit: 32Gi
    gpu_limit: "1"
    storage_quota: 100Gi
    priority: high
  billing:
    enabled: true
    stripe_customer_id: "cus_xxxxxxxxxxxxx"
    spend_limit_usd: 500
  networking:
    custom_domain: "ai.propartner.io"
    tls_enabled: true
EOF
```

### 4.3 Enterprise Tenant

```bash
cat << 'EOF' | kubectl apply -f -
apiVersion: roma.io/v1
kind: RomaTenant
metadata:
  name: tenant-enterprise-acme
  namespace: roma-system
spec:
  tier: enterprise
  plan:
    cpu_limit: "32"
    memory_limit: 128Gi
    gpu_limit: "4"
    storage_quota: 500Gi
    priority: critical
  billing:
    enabled: true
    stripe_customer_id: "cus_xxxxxxxxxxxxx"
    spend_limit_usd: 0  # unlimited
  networking:
    custom_domain: "platform.acmecorp.com"
    tls_enabled: true
  branding:
    logo_url: "https://acmecorp.com/logo.png"
    primary_color: "#0066CC"
    company_name: "Acme Corporation"
    support_email: "platform-support@acmecorp.com"
EOF
```

### 4.4 Verify Tenant

```bash
kubectl get romatenants -n roma-system

kubectl describe romatenant tenant-pro-demo -n roma-system
# Check Status.conditions for provisioning state
```

---

## Step 5 — Branding

### 5.1 Branding via RomaTenant CR

```yaml
spec:
  branding:
    logo_url: "https://yourbrand.com/logo.png"
    primary_color: "#FF6B00"
    secondary_color: "#1A1A2E"
    company_name: "Your Company"
    support_email: "support@yourbrand.com"
    terms_url: "https://yourbrand.com/terms"
    privacy_url: "https://yourbrand.com/privacy"
```

### 5.2 Kong Gateway Branding

Kong automatically injects tenant branding into responses via plugin:

```bash
# Check branding plugin logs:
kubectl logs -n roma-system -l app=kong -c kong | grep branding
```

### 5.3 Email Branding

Set in tenant spec for transactional emails (receipts, invoices):

```yaml
spec:
  branding:
    from_name: "Your Company Platform"
    from_email: "no-reply@yourbrand.com"
```

---

## Step 6 — Domain + TLS

### 6.1 Cert-Manager (auto-provisioned by ROMA)

Let's Encrypt certificates are auto-provisioned via cert-manager:

```bash
# Check certificate status:
kubectl get certificates -n roma-system

# Verify TLS:
kubectl get CertificateRequest -n roma-system
```

### 6.2 Custom Domain Setup

1. **Add DNS A record** pointing to your cluster node IP:

```
ai.partner.com  A  192.168.1.100
```

2. **Update tenant with custom domain:**

```bash
kubectl patch romatenant tenant-pro-demo -n roma-system \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/networking/custom_domain", "value": "ai.partner.com"}]'
```

3. **Verify certificate:**

```bash
kubectl describe certificate -n roma-system | grep -A5 "ai.partner.com"
```

### 6.3 Force HTTPS

Kong gateway enforces HTTPS via plugin. All HTTP traffic redirects to HTTPS automatically.

---

## Step 7 — Stripe Payments

### 7.1 Configure Stripe Webhook

1. Go to [dashboard.stripe.com/webhooks](https://dashboard.stripe.com/webhooks)
2. Add endpoint: `https://your-domain.com/api/stripe-webhook`
3. Select events:
   - `checkout.session.completed`
   - `payment_intent.succeeded`
   - `payment_intent.payment_failed`
   - `customer.subscription.updated`
4. Copy signing secret (starts with `whsec_`)

### 7.2 Save Secrets to Zo Settings

Go to [Settings > Advanced](/?t=settings&s=advanced) → Secrets:

| Secret | Value |
|--------|-------|
| `STRIPE_SECRET_KEY` | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` |

### 7.3 Update Tenant with Stripe Customer

```bash
kubectl patch romatenant tenant-pro-demo -n roma-system \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/billing/stripe_customer_id", "value": "cus_xxxxx"}]'
```

### 7.4 Verify Webhook

```bash
# Send test event from Stripe dashboard → check pod logs:
kubectl logs -n roma-system -l app=roma \
  --tail=100 | grep -i stripe
```

---

## Step 8 — Verification

### Health Checks

```bash
# 1. Cluster health:
kubectl get nodes -o wide

# 2. ROMA pods:
kubectl get pods -n roma-system

# 3. Storage classes:
kubectl get storageclass

# 4. Web service:
curl -I https://your-domain.com/healthz
# Expected: HTTP 200

# 5. Kong admin:
curl http://localhost:8001/health
# Expected: {"nginx_workers":1,"workers":1,"memory":...}

# 6. MinIO:
curl http://localhost:9001/minio/health/live
# Expected: {"status":"ok"}

# 7. Tenant provisioning:
kubectl get romatenants -n roma-system
# Expected: All tenants in Ready condition
```

### Monitoring

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | `http://<node>:30080` | `admin` / `prom-operator` |
| Longhorn UI | `http://<node>:30800` | — |
| MinIO Console | `http://<node>:9001` | `minioadmin` / `minioadmin123` |
| Rook Ceph Dashboard | `http://<node>:7000` | — |
| Kong Admin | `http://localhost:8001` | — |

### Get Grafana Password

```bash
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

---

## Troubleshooting

### Pods not starting

```bash
kubectl describe pod <pod-name> -n roma-system
kubectl logs <pod-name> -n roma-system --previous
```

### GPU not detected

```bash
nvidia-smi
# If empty → reinstall NVIDIA driver:
sudo system76-driver nvidia
sudo system76-power graphics nvidia
reboot
```

### Storage provisioning fails

```bash
# Check Longhorn:
kubectl get volumes -n longhorn-system
kubectl describe volumes -n longhorn-system <volume-name>

# Check Rook Ceph:
kubectl get cephcluster -n rook-ceph
kubectl get pools -n rook-ceph
```

### cert-manager not issuing certificate

```bash
kubectl describe certificate -n roma-system
kubectl logs -n cert-manager deploy/cert-manager --tail=50

# Check clusterissuers:
kubectl get clusterissuer
kubectl describe clusterissuer letsencrypt-prod
```

### Tailscale not connecting

```bash
tailscale status
sudo tailscale up --authkey=<key>
sudo tailscale funnel 443
```

### Kong gateway issues

```bash
kubectl exec -n roma-system -it svc/roma-kong-kong-proxy -- kong health
kubectl logs -n roma-system -l app=kong --tail=100
```

---

## Quick Reference

```bash
# Full deploy (cluster profile):
sudo PROFILE=cluster bash pop-os-setup-v5.sh

# Install ROMA:
helm install roma oci://ghcr.io/mahaasur13-sys/charts/roma-execution-bridge \
  --version 1.0.0 -n roma-system --create-namespace

# Create Pro tenant:
cat << 'EOF' | kubectl apply -f -
apiVersion: roma.io/v1
kind: RomaTenant
metadata:
  name: tenant-pro
  namespace: roma-system
spec:
  tier: pro
  plan:
    cpu_limit: "8"
    memory_limit: 32Gi
    gpu_limit: "1"
    storage_quota: 100Gi
EOF

# Monitoring:
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 30080:80 &
```