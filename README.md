
## On your local workstation (Linux)

#### Generate TLS certificates
##### Download required binaries
```
{
  CFSSL_VERSION=1.6.5
  wget -q --show-progress \
    https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VERSION}/cfssl_${CFSSL_VERSION}_linux_amd64 \
    https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VERSION}/cfssljson_${CFSSL_VERSION}_linux_amd64
  
  chmod +x cfssl_${CFSSL_VERSION}_linux_amd64 cfssljson_${CFSSL_VERSION}_linux_amd64
  mv cfssl_${CFSSL_VERSION}_linux_amd64 /usr/local/bin/cfssl && mv cfssljson_${CFSSL_VERSION}_linux_amd64 /usr/local/bin/cfssljson
}
```
##### Create a Certificate Authority (CA)
> We then use this CA to create other TLS certificates
```
{

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
      "O": "Team 1",
      "OU": "Etcd-CA"
    }
  ]
}
EOF

cfssl gencert -initca ca-csr.json | cfssljson -bare ca

}
```
##### Create TLS certificates
```
{

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
      "O": "TEAM 1",
      "OU": "Etcd"
    }
  ]
}
EOF

cfssl gencert -ca=ca.pem -ca-key=ca-key.pem -config=ca-config.json -profile=etcd etcd-csr.json | cfssljson -bare etcd

}
```
##### Copy the certificates to etcd nodes
```
{

declare -a NODES=(10.0.0.11 10.0.0.12 10.0.0.13)

for node in ${NODES[@]}; do
  scp ca.pem etcd.pem etcd-key.pem root@$node: 
done

}
```

## On all etcd nodes

> Perform all commands logged in as **root** user or prefix each command with **sudo** as appropriate

##### Copy the certificates to a standard location
```
{
  mkdir -p /etc/etcd/pki
  mv ca.pem etcd.pem etcd-key.pem /etc/etcd/pki/
  ls -la /etc/etcd/pki/
}
```

##### Download etcd & etcdctl binaries from Github
```
{
  ETCD_VERSION=v3.5.21

  echo "[*] Downloading etcd ${ETCD_VERSION}..."
  wget -q --show-progress "https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz"

  echo "[*] Extracting etcd..."
  tar -zxf etcd-${ETCD_VERSION}-linux-amd64.tar.gz

  echo "[*] Moving binaries to /usr/local/bin/..."
  sudo mv etcd-${ETCD_VERSION}-linux-amd64/etcd* /usr/local/bin/

  echo "[*] Cleaning up..."
  rm -rf etcd-${ETCD_VERSION}-linux-amd64*
  etcdctl version
}
```

##### Create systemd unit file for etcd service
> Set NODE_IP to the correct IP of the machine where you are running this
```
{

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
  --initial-cluster-token etcd-cluster-1 \\
  --initial-cluster etcd-1=https://${ETCD1_IP}:2380,etcd-2=https://${ETCD2_IP}:2380,etcd-3=https://${ETCD3_IP}:2380 \\
  --initial-cluster-state new
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

}
```

##### Enable and Start etcd service
```
{
  systemctl daemon-reload
  systemctl enable --now etcd
}
```

##### Verify Etcd cluster status
> In any one of the etcd nodes
```
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/etcd/pki/ca.pem \
  --cert=/etc/etcd/pki/etcd.pem \
  --key=/etc/etcd/pki/etcd-key.pem \
  member list --write-out=table
```
Better to export these as environment variables and connect to the clutser instead of a specific node
```
cat <<EOT | sudo tee /etc/profile.d/etcdctl.sh > /dev/null
export ETCDCTL_API=3
export ETCDCTL_ENDPOINTS="https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379"
export ETCDCTL_CACERT="/etc/etcd/pki/ca.pem"
export ETCDCTL_CERT="/etc/etcd/pki/etcd.pem"
export ETCDCTL_KEY="/etc/etcd/pki/etcd-key.pem"
EOT

sudo chmod +x /etc/profile.d/etcdctl.sh
source /etc/profile.d/etcdctl.sh
```
And now its a lot easier
```
etcdctl member list --write-out=table
etcdctl endpoint status --write-out=table
etcdctl endpoint health --write-out=table
```
