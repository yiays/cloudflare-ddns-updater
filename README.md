Cloudflare Dynamic DNS (DDNS) Updater
===

Periodically checks the WAN IP address of this device by calling [a WAN IP echo server](https://ipfy.org) or IPv6 interface information and submit the change to the provided Cloudflare zone and DNS record, if necessary.

Cloudflare API:
`https://api.cloudflare.com/client/v4/zones/:zone_id/dns_records/:dns_record_id`

```
$ ./cloudflare-ddns-updater.py -h
usage: cloudflare-ddns-updater.py [-h] [--ipv4_record_id IPV4_RECORD_ID] [--ipv6_record_id IPV6_RECORD_ID] [--interface INTERFACE] [--frequency MIN MAX] [--log-dir LOG_DIR] zone_id api_token

Periodically checks the global IPv6 address of this device and updates a Cloudflare AAAA DNS record.

positional arguments:
  zone_id               The Cloudflare Zone ID.
  api_token             Cloudflare API Token with Edit zone DNS permissions.

options:
  -h, --help            show this help message and exit
  --ipv4_record_id IPV4_RECORD_ID
                        The Cloudflare A DNS Record ID. Optional.
  --ipv6_record_id IPV6_RECORD_ID
                        The Cloudflare AAAA DNS Record ID. Optional.
  --interface INTERFACE
                        Optional network interface name (e.g., eth0, enp3s0) to read the stable IPv6 address from.
  --frequency MIN MAX
  --log-dir LOG_DIR     Directory for rotated log files.
```

# Example to run as a service on a Raspberry Pi

## Create a shell script

```shell
vim.tiny /home/{username}/cloudflare-ddns-updater/update-ddns.sh
```

Content:

```shell
#!/usr/bin/env bash
/usr/bin/python3 /home/{username}/cloudflare-ddns-updater/cloudflare-ddns-updater.py {zone_id} {dns_record_id} {api_token} --log-dir /home/{username}/cloudflare-ddns-updater/log
```

## Create a service

```shell
sudo vim.tiny /etc/systemd/system/cloudflare-ddns-updater.service
```

Content:

```shell
[Unit]
Description=Update Cloudflare DNS record to point to this device's public IP.
After=network-online.target

[Service]
ExecStart=/home/{username}/cloudflare-ddns-updater/update-ddns.sh

[Install]
WantedBy=multi-user.target
```

## Register and enable

1. Reload `systemd` to pick it up

```shell
sudo systemctl daemon-reload
```

2. Enable it to start on boot

```shell
sudo systemctl enable cloudflare-ddns-updater.service
```


3. Start it right now

```shell
sudo systemctl start cloudflare-ddns-updater.service
```


4. Check status

```shell
systemctl status cloudflare-ddns-updater.service
```

# Got issue?

The easiest way to run this is by using [pipenv](https://github.com/pypa/pipenv). The installation steps on MacOS (with [Homebrew](https://brew.sh/)) is roughly:
```
$ brew install pipenv

# Run this in the project directory, e.g. ~/cloudflare-ddns-updater/
$ pipenv install
```

To run:
```
# Run this in the project directory, e.g. ~/cloudflare-ddns-updater/
$ pipenv shell

# Inside the shell, run the script.
$ ./cloudflare-ddns-updater.py -h
```

original by James Margatan, IPv6 version by Yiays
