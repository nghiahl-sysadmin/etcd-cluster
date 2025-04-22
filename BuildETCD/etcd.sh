#!/bin/bash

set -eux

timedatectl set-timezone Asia/Ho_Chi_Minh
timedatectl set-ntp true

mkdir -p /etc/etcd/pki /etc/etcd/snapshot
mv /opt/etcd/*.pem /etc/etcd/pki/
ls -la /etc/etcd/pki/

ETCD_VERSION=v3.5.21
wget -q --show-progress "https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz"
tar -zxf etcd-${ETCD_VERSION}-linux-amd64.tar.gz
mv etcd-${ETCD_VERSION}-linux-amd64/etcd* /usr/local/bin/
rm -rf etcd-${ETCD_VERSION}-linux-amd64*
etcdctl version

interface=$(ip -o link show | awk -F': ' '/state UP/ && $2 != "lo" && $2 !~ /^bond/ {print $2}')
NODE_IP=$(ip addr show $interface | awk '$1 == "inet" {gsub(/\/.*$/, "", $2); print $2}')

ETCD_NAME=$(hostname -s)
ETCD1_IP="1.55.119.22"
ETCD2_IP="1.55.119.23"
ETCD3_IP="1.55.119.24"

cat <<EOF | sudo tee /etc/hosts > /dev/null
127.0.0.1 localhost
$ETCD1_IP etcd-1
$ETCD2_IP etcd-2
$ETCD3_IP etcd-3
EOF

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

systemctl restart rsyslog
systemctl daemon-reload
systemctl enable --now etcd

cat <<EOT | sudo tee /etc/profile.d/etcdctl.sh > /dev/null
export ETCDCTL_API=3
export ETCDCTL_ENDPOINTS="https://1.55.119.22:2379,https://1.55.119.23:2379,https://1.55.119.24:2379"
export ETCDCTL_CACERT="/etc/etcd/pki/ca.pem"
export ETCDCTL_CERT="/etc/etcd/pki/etcd.pem"
export ETCDCTL_KEY="/etc/etcd/pki/etcd-key.pem"
EOT

chmod +x /etc/profile.d/etcdctl.sh
source /etc/profile.d/etcdctl.sh

etcdctl member list --write-out=table
etcdctl endpoint status --write-out=table
etcdctl endpoint health --write-out=table
