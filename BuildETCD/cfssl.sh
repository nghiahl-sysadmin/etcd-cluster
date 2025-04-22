#!/bin/bash

set -eux

CFSSL_VERSION=1.6.5
wget -q --show-progress \
  https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VERSION}/cfssl_${CFSSL_VERSION}_linux_amd64 \
  https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VERSION}/cfssljson_${CFSSL_VERSION}_linux_amd64

chmod +x cfssl_${CFSSL_VERSION}_linux_amd64 cfssljson_${CFSSL_VERSION}_linux_amd64
mv cfssl_${CFSSL_VERSION}_linux_amd64 /usr/local/bin/cfssl && mv cfssljson_${CFSSL_VERSION}_linux_amd64 /usr/local/bin/cfssljson

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
  "CN": "Root CA",
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

ETCD1_IP="1.55.119.22"
ETCD2_IP="1.55.119.23"
ETCD3_IP="1.55.119.24"

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

declare -a NODES=(1.55.119.22 1.55.119.23 1.55.119.24)
for node in ${NODES[@]}; do
  scp ca.pem etcd.pem etcd-key.pem root@$node:/opt/etcd
done

ETCD_VERSION=v3.5.21
wget -q --show-progress "https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz"
tar -zxf etcd-${ETCD_VERSION}-linux-amd64.tar.gz
mv etcd-${ETCD_VERSION}-linux-amd64/etcd* /usr/local/bin/
rm -rf etcd-${ETCD_VERSION}-linux-amd64*
etcdctl version

cat <<EOT | sudo tee /etc/profile.d/etcdctl.sh > /dev/null
export ETCDCTL_API=3
export ETCDCTL_ENDPOINTS="https://1.55.119.22:2379,https://1.55.119.23:2379,https://1.55.119.24:2379"
export ETCDCTL_CACERT="/opt/cfssl/ca.pem"
export ETCDCTL_CERT="/opt/cfssl/etcd.pem"
export ETCDCTL_KEY="/opt/cfssl/etcd-key.pem"
EOT

chmod +x /etc/profile.d/etcdctl.sh
source /etc/profile.d/etcdctl.sh
