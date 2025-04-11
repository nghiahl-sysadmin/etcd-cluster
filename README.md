# 🛠️ Hướng dẫn triển khai cụm Etcd 3-node với TLS trên Ubuntu 24.04 LTS

---

## 🧰 1. Chuẩn bị môi trường

### ✅ Yêu cầu:
- 3 máy chủ cài đặt **Ubuntu Server 24.04 LTS**
- Kết nối mạng nội bộ giữa các node
- Quyền **root** hoặc có thể sử dụng `sudo`
- Tắt firewall nội bộ hoặc mở các port cần thiết: `2379`, `2380`

---

### 📦 Máy chủ & thông tin IP:

| Hostname | IP         | Vai trò              |
|----------|------------|----------------------|
| etcd-1   | 10.0.0.11  | Leader hoặc Follower |
| etcd-2   | 10.0.0.12  | Leader hoặc Follower |
| etcd-3   | 10.0.0.13  | Leader hoặc Follower |

---

### ⚙️ Thiết lập cơ bản trên **cả 3 máy chủ**:

```bash
# Cập nhật hệ thống
apt update && apt upgrade -y && apt -y autoremove

# Đặt hostname phù hợp trên từng máy
sudo hostnamectl set-hostname etcd-1  # Thay đổi phù hợp với từng node

# Cập nhật file hosts để các node nhận diện được nhau
cat <<EOF | sudo tee /etc/hosts > /dev/null
127.0.0.1 localhost
10.0.0.11 etcd-1
10.0.0.12 etcd-2
10.0.0.13 etcd-3
EOF
```

## 💻 Trên trạm local (Linux)

### ✔️ Cài chứng thư CFSSL

#### Tải các binary cần thiết
```bash
CFSSL_VERSION=1.6.5
wget -q --show-progress \
  https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VERSION}/cfssl_${CFSSL_VERSION}_linux_amd64 \
  https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VERSION}/cfssljson_${CFSSL_VERSION}_linux_amd64

chmod +x cfssl_${CFSSL_VERSION}_linux_amd64 cfssljson_${CFSSL_VERSION}_linux_amd64
mv cfssl_${CFSSL_VERSION}_linux_amd64 /usr/local/bin/cfssl && mv cfssljson_${CFSSL_VERSION}_linux_amd64 /usr/local/bin/cfssljson
```

#### Tạo Certificate Authority (CA)
```bash
cat > ca-config.json <<EOF
{
    "signing": {
        "default": {
            "expiry": "87600h"
        },
        "profiles": {
            "etcd": {
                "expiry": "87600h",
                "usages": ["signing","key encipherment","server auth","client auth"]
            }
        }
    }
}
EOF

cat > ca-csr.json <<EOF
{
  "CN": "Etcd Cluster",
  "key": {
    "algo": "rsa",
    "size": 2048
  },
  "names": [
    {
      "C": "VN",
      "ST": "Ho Chi Minh",
      "OU": "CA"
    }
  ]
}
EOF

cfssl gencert -initca ca-csr.json | cfssljson -bare ca
```

#### Tạo chứng chỉ TLS cho etcd
```bash
ETCD1_IP="10.0.0.11"
ETCD2_IP="10.0.0.12"
ETCD3_IP="10.0.0.13"

cat > etcd-csr.json <<EOF
{
  "CN": "Etcd",
  "hosts": [
    "localhost",
    "127.0.0.1",
    "${ETCD1_IP}",
    "${ETCD2_IP}",
    "${ETCD3_IP}"
  ],
  "key": {
    "algo": "rsa",
    "size": 2048
  },
  "names": [
    {
      "C": "VN",
      "ST": "Ho Chi Minh",
      "OU": "Etcd Cluster"
    }
  ]
}
EOF

cfssl gencert -ca=ca.pem -ca-key=ca-key.pem -config=ca-config.json -profile=etcd etcd-csr.json | cfssljson -bare etcd
```

#### Copy chứng chỉ tới các node etcd
```bash
declare -a NODES=(10.0.0.11 10.0.0.12 10.0.0.13)
for node in ${NODES[@]}; do
  scp ca.pem etcd.pem etcd-key.pem root@$node:
done
```

## 💪 Trên mỗi node etcd

> Đăng nhập với quyền `root` hoặc dùng `sudo`

#### Copy TLS vào đúng đường dẫn
```bash
mkdir -p /etc/etcd/pki /etc/etcd/snapshot
mv ca.pem etcd.pem etcd-key.pem /etc/etcd/pki/
ls -la /etc/etcd/pki/
```

#### Cài đặt etcd và etcdctl
```bash
ETCD_VERSION=v3.5.21
wget -q --show-progress "https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz"
tar -zxf etcd-${ETCD_VERSION}-linux-amd64.tar.gz
mv etcd-${ETCD_VERSION}-linux-amd64/etcd* /usr/local/bin/
rm -rf etcd-${ETCD_VERSION}-linux-amd64*
etcdctl version
```

#### Khai báo unit file cho systemd
```bash
NODE_IP="10.0.0.11"
ETCD_NAME=$(hostname -s)
ETCD1_IP="10.0.0.11"
ETCD2_IP="10.0.0.12"
ETCD3_IP="10.0.0.13"

cat <<EOF >/etc/systemd/system/etcd.service
[Unit]
Description=etcd

[Service]
Type=notify
ExecStart=/usr/local/bin/etcd \\
  --name ${ETCD_NAME} \\
  --data-dir=/var/lib/etcd \\
  --cert-file=/etc/etcd/pki/etcd.pem \\
  --key-file=/etc/etcd/pki/etcd-key.pem \\
  --peer-cert-file=/etc/etcd/pki/etcd.pem \\
  --peer-key-file=/etc/etcd/pki/etcd-key.pem \\
  --trusted-ca-file=/etc/etcd/pki/ca.pem \\
  --peer-trusted-ca-file=/etc/etcd/pki/ca.pem \\
  --peer-client-cert-auth \\
  --client-cert-auth \\
  --initial-advertise-peer-urls https://${NODE_IP}:2380 \\
  --listen-peer-urls https://${NODE_IP}:2380 \\
  --advertise-client-urls https://${NODE_IP}:2379 \\
  --listen-client-urls https://${NODE_IP}:2379,https://127.0.0.1:2379 \\
  --initial-cluster-token etcd-cluster \\
  --initial-cluster etcd-1=https://${ETCD1_IP}:2380,etcd-2=https://${ETCD2_IP}:2380,etcd-3=https://${ETCD3_IP}:2380 \\
  --initial-cluster-state new
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
cat << 'EOF' > /etc/rsyslog.d/30-etcd.conf
if $programname == 'etcd' then /var/log/etcd.log
& stop
EOF
touch /var/log/etcd.log
chown syslog:adm /var/log/etcd.log
chmod 640 /var/log/etcd.log
```

#### Khởi động etcd
```bash
systemctl restart rsyslog
systemctl daemon-reload
systemctl enable --now etcd
```

#### Kiểm tra tình trạng cluster
```bash
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/etcd/pki/ca.pem \
  --cert=/etc/etcd/pki/etcd.pem \
  --key=/etc/etcd/pki/etcd-key.pem \
  member list --write-out=table
```

#### Thiết lập environment biến
```bash
cat <<EOT | sudo tee /etc/profile.d/etcdctl.sh > /dev/null
export ETCDCTL_API=3
export ETCDCTL_ENDPOINTS="https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379"
export ETCDCTL_CACERT="/etc/etcd/pki/ca.pem"
export ETCDCTL_CERT="/etc/etcd/pki/etcd.pem"
export ETCDCTL_KEY="/etc/etcd/pki/etcd-key.pem"
EOT

chmod +x /etc/profile.d/etcdctl.sh
source /etc/profile.d/etcdctl.sh
```

Giờ bạn có thể dùng:
```bash
etcdctl member list --write-out=table
etcdctl endpoint status --write-out=table
etcdctl endpoint health --write-out=table
```

---

# 🧵 ETCD Snapshot & Khôi phục với TLS

## 📆 Tạo snapshot
```bash
ETCDCTL_ENDPOINTS=https://10.0.0.11:2379 etcdctl snapshot save /etc/etcd/snapshot/etcd-snapshot-$(date +"%Y-%m-%d").db
```

## 🔍 Kiểm tra snapshot
```bash
etcdutl snapshot status /etc/etcd/snapshot/etcd-snapshot-$(date +"%Y-%m-%d").db --write-out=table
```

## 🌁 Backup thư mục etcd hiện tại
```bash
mv /var/lib/etcd /var/lib/etcd.bak-$(date +"%Y-%m-%d")
```

## ♻️ Khôi phục snapshot (chạy trên tất cả các node)
```bash
systemctl stop etcd.service # Dừng chạy service etcd trên toàn bộ node trước khi restore tránh xung đột database

# Lưu ý chỉ cần lấy 1 bản restore của một trong 3 node để thực hiện trên toàn bộ node etcd, vì bản snapshot đều có cùng một trạng thái dữ liệu nhất quán
etcdutl snapshot restore /etc/etcd/snapshot/etcd-snapshot-$(date +"%Y-%m-%d").db \
  --name etcd-1 \
  --initial-cluster "etcd-1=https://10.0.0.11:2380,etcd-2=https://10.0.0.12:2380,etcd-3=https://10.0.0.13:2380" \
  --initial-advertise-peer-urls https://10.0.0.11:2380 \
  --data-dir /var/lib/etcd \
  --initial-cluster-token etcd-cluster
```
