# WireGuard/AmneziaWG VPN Mesh Module
# Creates encrypted mesh between all cluster nodes

resource "local_file" "wg_conf_template" {
  filename = "${path.module}/wg-template.conf"
  content  = <<-EOT
# WireGuard config for ${node_name}
# Node: ${node_name} | Role: ${role}

[Interface]
Address = ${wg_ip}
PrivateKey = ${private_key}
ListenPort = ${listen_port}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ${外网卡} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ${外网卡} -j MASQUERADE

${peers}
EOT
}

resource "local_file" "amnezia_service" {
  filename = "${path.module}/amnezia-${node_name}.service"
  content  = <<-EOT
[Unit]
Description=AmneziaWG mesh peer ${node_name}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/amneziawg-client install ${wg_ip}:51820
ExecStart=/usr/local/bin/amneziawg-client set-private-key ${private_key}
${peer_exec_lines}
ExecStop=/usr/local/bin/amneziawg-client stop

[Install]
WantedBy=multi-user.target
EOT
}
