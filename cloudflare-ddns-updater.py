#!/usr/bin/env python3

# Periodically update Cloudflare with the current IPv4 and IPv6 addresses
#
# original by James Margatan
# adapted for IPv6 by Yiays

import argparse
import errno
import ipaddress
import json
import logging
import logging.handlers
import os
import random
import subprocess
import time

import requests

# Const for Cloudflare request headers.
CF_HEADER_KEY = 'Authorization'
CF_DNS_RECORD_IP_FIELD = 'content'
CF_ZONE_AND_DNS_RECORDS_URL_TEMPLATE = 'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records'
CF_ZONE_AND_DNS_RECORD_URL_TEMPLATE = 'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{dns_record_id}'

# IPv4 echo server
WAN_IP_ECHO_SERVER = 'https://api.ipify.org'
# IPv6 echo server (only used as a fallback)
WAN_IPV6_ECHO_SERVER = 'https://api64.ipify.org'

LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def get_stable_ipv6_from_interface(interface=None):
    """Finds the non-temporary global IPv6 address assigned to the local Linux host."""
    cmd = ['ip', '-6', '-j', 'addr', 'show', 'scope', 'global']
    if interface:
        cmd.extend(['dev', interface])

    try:
        output = subprocess.check_output(cmd, text=True)
        interfaces = json.loads(output)
        for iface in interfaces:
            for addr_info in iface.get('addr_info', []):
                # Skip temporary/privacy addresses and deprecated addresses
                if addr_info.get('temporary') or addr_info.get('deprecated'):
                    continue
                ip_str = addr_info.get('local')
                if ip_str:
                    ip_obj = ipaddress.IPv6Address(ip_str)
                    if ip_obj.is_global:
                        return str(ip_obj)
    except Exception as e:
        LOG.warning(f'Local interface IPv6 lookup failed ({e}), falling back to echo server.')
    return None


def get_wan_ipv6(interface=None):
    # 1. Prefer local non-temporary global IPv6 address so router firewall rules stay valid
    local_ipv6 = get_stable_ipv6_from_interface(interface)
    if local_ipv6:
        return local_ipv6

    # 2. Fallback to IPv6-only echo server
    r = requests.get(WAN_IPV6_ECHO_SERVER, timeout=10)
    try:
        r.raise_for_status()
        ip_str = r.text.strip()
        # Validate that the returned address is genuinely IPv6
        return str(ipaddress.IPv6Address(ip_str))
    except Exception as e:
        raise RuntimeError('Unable to get WAN IPv6 address.') from e


def get_wan_ip():
    r = requests.get(WAN_IP_ECHO_SERVER, timeout=10)
    try:
        r.raise_for_status()
        ip_str = r.text.strip()
        # Validate that the returned address is genuinely IPv4
        return str(ipaddress.IPv4Address(ip_str))
    except Exception as e:
        raise RuntimeError('Unable to get WAN IPv4 address.') from e


def get_cloudflare_dns_record_url(zone_id, dns_record_id):
    return CF_ZONE_AND_DNS_RECORD_URL_TEMPLATE.format(
        zone_id=zone_id,
        dns_record_id=dns_record_id)


def get_cloudflare_dns_records_url(zone_id):
    return CF_ZONE_AND_DNS_RECORDS_URL_TEMPLATE.format(
        zone_id=zone_id)


def get_cloudflare_auth_headers(key):
    return {
        CF_HEADER_KEY: "Bearer " + key,
        'Content-Type': 'application/json'
    }


def get_cloudflare_dns_record(cfg, record_id):
    cf_url = get_cloudflare_dns_record_url(cfg.zone_id, record_id)
    cf_headers = get_cloudflare_auth_headers(cfg.key)

    r = requests.get(cf_url, headers=cf_headers, timeout=10)
    try:
        r.raise_for_status()
        record = r.json().get('result', {})
        if record.get('type') not in ('AAAA', 'A'):
            raise RuntimeError(f"Target Cloudflare DNS record is type '{record.get('type')}', expected 'AAAA' or 'A'.")
        return record
    except Exception as e:
        raise RuntimeError(f'Unable to get Cloudflare DNS record for [zone_id: {cfg.zone_id}] [dns_record_id: {record_id}].') from e


def get_cloudflare_dns_records(cfg):
    cf_url = get_cloudflare_dns_records_url(cfg.zone_id)
    cf_headers = get_cloudflare_auth_headers(cfg.key)

    r = requests.get(cf_url, headers=cf_headers, timeout=10)
    try:
        r.raise_for_status()
        records = r.json().get('result', {})
        return records
    except Exception as e:
        raise RuntimeError(f'Unable to get Cloudflare DNS records for [zone_id: {cfg.zone_id}].') from e


def get_ip_from_dns_record(dns_record):
    ip_from_dns_record = dns_record.get(CF_DNS_RECORD_IP_FIELD)
    if not ip_from_dns_record:
        raise RuntimeError(f'Unable to get IP address from [dns_record: {dns_record}].')
    # Normalize IP representation (e.g., compressed vs expanded) for accurate comparison
    if '.' in ip_from_dns_record:
        return str(ipaddress.IPv4Address(ip_from_dns_record))
    return str(ipaddress.IPv6Address(ip_from_dns_record))


class Config:
    def __init__(self, args):
        self.zone_id = args.zone_id
        self.ipv4_record_id = args.ipv4_record_id
        self.ipv6_record_id = args.ipv6_record_id
        self.key = args.api_token
        self.interface = args.interface
        self.min_frequency = args.frequency[0]
        self.max_frequency = args.frequency[1]
        self.log_dir = args.log_dir


def format_address_records(records):
    filtered = [r for r in records if r.get("type") in {'A','AAAA'}]
    blocks = [
        "\t".join([
            f"{r.get('id')}",
            f"{r.get('type')}",
            f"{r.get('name')}",
        ])
        for r in filtered
    ]
    return (
        "CLOUDFLARE ID\t\t\t\tTYPE\tNAME\n" +
        '='*80 + '\n' +
        "\n".join(blocks) + '\n\n'
    )


def check(cfg):
    LOG.info('Initiating IP check and update...')
    if cfg.ipv4_record_id:
        wan_ip_v4 = get_wan_ip()
        record_v4 = get_cloudflare_dns_record(cfg, cfg.ipv4_record_id)
        update(cfg, wan_ip_v4, record_v4)

    if cfg.ipv6_record_id:
        wan_ip_v6 = get_wan_ipv6(cfg.interface)
        record_v6 = get_cloudflare_dns_record(cfg, cfg.ipv6_record_id)
        update(cfg, wan_ip_v6, record_v6)

    if not cfg.ipv4_record_id and not cfg.ipv6_record_id:
        LOG.error('No IPv4 or IPv6 record specified, you must specify at least one!')
        records = get_cloudflare_dns_records(cfg)
        LOG.info('Available DNS records;\n\n' + format_address_records(records))


def update(cfg, wan_ip, record):
    stored_ip = get_ip_from_dns_record(record)
    if wan_ip == stored_ip:
        LOG.info(f'No update needed. [wan_ip and ip_from_dns_record: {wan_ip}] match.')
        return

    LOG.info(f'[wan_ip: {wan_ip}] and [ip_from_dns_record: {stored_ip}] differ. Initiating update...')

    record[CF_DNS_RECORD_IP_FIELD] = wan_ip
    update_cloudflare_dns_record(cfg, record)

    LOG.info('Update successful.')


def update_cloudflare_dns_record(cfg, dns_record):
    cf_url = get_cloudflare_dns_record_url(cfg.zone_id, cfg.dns_record_id)
    cf_headers = get_cloudflare_auth_headers(cfg.key)

    # PATCH only the content field to avoid sending read-only metadata back to Cloudflare
    payload = {'content': dns_record[CF_DNS_RECORD_IP_FIELD]}
    r = requests.patch(cf_url, headers=cf_headers, json=payload, timeout=10)
    try:
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f'Unable to update Cloudflare DNS record for [zone_id: {cfg.zone_id}] [dns_record_id: {cfg.dns_record_id}].') from e


def ensure_log_directory_exist(log_dir):
    if os.path.exists(log_dir):
        return
    try:
        os.makedirs(log_dir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise RuntimeError(f'Unable to create [log_dir: {log_dir}].') from e


def main():
    arg_parser = argparse.ArgumentParser(description='Periodically checks the global IPv6 address of this device and updates a Cloudflare AAAA DNS record.')
    arg_parser.add_argument('zone_id', help='The Cloudflare Zone ID.')
    arg_parser.add_argument('api_token', help='Cloudflare API Token with Edit zone DNS permissions.')
    arg_parser.add_argument('--ipv4_record_id', help='The Cloudflare A DNS Record ID. Optional.')
    arg_parser.add_argument('--ipv6_record_id', help='The Cloudflare AAAA DNS Record ID. Optional.')
    arg_parser.add_argument('--interface', default=None, help='Optional network interface name (e.g., eth0, enp3s0) to read the stable IPv6 address from.')
    arg_parser.add_argument('--frequency', nargs=2, default=[2, 5], metavar=('MIN', 'MAX'), type=int)
    arg_parser.add_argument('--log-dir', help='Directory for rotated log files.')

    args = arg_parser.parse_args()
    cfg = Config(args)

    if cfg.log_dir is not None:
        ensure_log_directory_exist(cfg.log_dir)
        log_file_name = f'{cfg.log_dir}/cloudflare-dns-updater.out'
        log_handler = logging.handlers.TimedRotatingFileHandler(log_file_name, when='midnight', backupCount=7)
        log_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        log_handler.setLevel(logging.INFO)
        LOG.addHandler(log_handler)
        LOG.propagate = False
    else:
        logging.basicConfig(format=LOG_FORMAT)

    LOG.info('Starting Cloudflare IPv6 DDNS Updater')

    while True:
        try:
            check(cfg)
        except Exception as e:
            LOG.exception(e)

        next_run_in_mins = random.randint(cfg.min_frequency, cfg.max_frequency)
        LOG.info(f'Script will be executed again in {next_run_in_mins} minute(s).')
        time.sleep(next_run_in_mins * 60)


if __name__ == '__main__':
    main()
