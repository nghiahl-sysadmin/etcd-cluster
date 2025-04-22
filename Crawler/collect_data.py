import requests
import etcd3
import json
import logging
from datetime import datetime, timedelta, timezone

# --- Configuration for etcd and NVD API ---
ETCD_HOST = '1.55.119.24'
ETCD_PORT = 2379
CA_CERT_PATH = '/opt/cfssl/ca.pem'
CERT_CERT_PATH = '/opt/cfssl/etcd.pem'
CERT_KEY_PATH = '/opt/cfssl/etcd-key.pem'

# Your NVD API key - make sure to keep this secure in production
NVD_API_KEY = "005e41c8-ad08-4d8d-9fb7-cb958cd058f3"

# Key prefix used in etcd to organize CVE data
ETCD_KEY_PREFIX = '/vulns/cve/'

# --- Logging Setup ---
# Configure log output format and level
log_mode = 'DEBUG'

logging.basicConfig(
    level=getattr(logging, log_mode),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- etcd Connection ---
def connect_to_etcd():
    """
    Establish a secure connection to etcd using mTLS.
    """
    return etcd3.client(
        host=ETCD_HOST,
        port=ETCD_PORT,
        ca_cert=CA_CERT_PATH,
        cert_cert=CERT_CERT_PATH,
        cert_key=CERT_KEY_PATH,
        timeout=10
    )


# --- Fetch CVEs from NVD ---
def fetch_recent_cve_entries(start_date: datetime, end_date: datetime):
    """
    Fetch CVE entries from NVD published between `start_date` and `end_date`.
    """
    start_str = start_date.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    end_str = end_date.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    params = {
        "pubStartDate": start_str,
        "pubEndDate": end_str
    }
    headers = {"apiKey": NVD_API_KEY}

    try:
        logging.info(f"[FETCH] Fetching CVEs from NVD between {start_str} and {end_str}")
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        cves = data.get("vulnerabilities", [])
        logging.info(f"[FETCH] Retrieved {len(cves)} CVEs.")
        return cves
    except Exception as e:
        logging.error(f"[FETCH] Failed to fetch CVEs: {e}")
        return []


# --- Parse CVE Entry ---
def extract_cve_summary_from_raw(cve_entry):
    """
    Extract core CVE metadata from a raw NVD entry.
    Supports metrics from CVSS v3.1, v3.0, and v4.0.
    """
    cve = cve_entry.get("cve", {})
    cve_id = cve.get("id")
    published = cve.get("published")
    modified = cve.get("lastModified")
    references = [r.get("url") for r in cve.get("references", []) if r.get("url")]

    base_score = None
    base_severity = None
    metrics = cve.get("metrics", {})

    # Try multiple CVSS versions in order of preference
    for key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV40"]:
        for m in metrics.get(key, []):
            data = m.get("cvssData", {})
            if data:
                base_score = data.get("baseScore")
                base_severity = data.get("baseSeverity")
                break
        if base_score is not None:
            break

    return {
        "cveId": cve_id,
        "datePublished": published,
        "dateModified": modified,
        "baseScore": base_score,
        "baseSeverity": base_severity,
        "references": references
    }


# --- Store into etcd ---
def store_cve_entries_to_etcd(etcd_client, cve_list):
    """
    Store parsed CVE entries into etcd, only if content differs from existing value.
    """
    if not etcd_client or not cve_list:
        logging.warning("[STORE] etcd client not ready or CVE list empty.")
        return

    allowed_status = ["Analyzed"]
    processed_keys = set()
    skipped = 0
    updated = 0
    failed = 0

    for cve_raw in cve_list:
        try:
            cve_data = cve_raw.get("cve", {})
            cve_id = cve_data.get("id")
            vuln_status = cve_data.get("vulnStatus", "")

            if vuln_status not in allowed_status:
                continue

            normalized_status = vuln_status.lower().replace(" ", "-")
            data = extract_cve_summary_from_raw(cve_raw)

            if not data or not data.get("cveId") or data.get("baseScore") is None or \
               data.get("baseSeverity") is None or data.get("references") is None:
                continue

            etcd_value = json.dumps(data, ensure_ascii=False, sort_keys=True)
            keys = []

            if cve_id.startswith("CVE-"):
                keys.append(f"{ETCD_KEY_PREFIX}{normalized_status}/{cve_id}")
            else:
                logging.debug(f"[SKIP] Unsupported ID format: {cve_id}")
                continue

            for key in keys:
                # Get existing value
                existing_value, _ = etcd_client.get(key)

                if existing_value is not None:
                    existing_value = existing_value.decode("utf-8")

                    # If value unchanged, skip
                    if json.loads(existing_value) == json.loads(etcd_value):
                        logging.debug(f"[SKIP] No change for key: {key}")
                        skipped += 1
                        continue

                # Update if new or changed
                etcd_client.put(key, etcd_value)
                logging.info(f"[ETCD] Updated key: {key}")
                processed_keys.add(key)
                updated += 1

        except Exception as e:
            logging.error(f"[STORE] Error storing CVE: {e}")
            failed += 1

    logging.info(f"[STORE] Done. Updated: {updated}, Skipped: {skipped}, Failed: {failed}")

# --- Main Pipeline ---
def run_pipeline():
    """
    Main entry point: connect to etcd, fetch latest CVEs from NVD,
    and persist valid entries to etcd storage.
    """
    etcd = connect_to_etcd()

    now = datetime.now(timezone.utc)
    start_of_year = datetime(now.year, 1, 1, tzinfo=timezone.utc)

    cve_entries = fetch_recent_cve_entries(start_of_year, now)
    store_cve_entries_to_etcd(etcd, cve_entries)


# --- Entry Point ---
if __name__ == "__main__":
    run_pipeline()

