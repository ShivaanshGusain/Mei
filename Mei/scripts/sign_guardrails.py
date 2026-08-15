"""
Admin tool: Sign the guardrails config after editing.
"""

import json
import yaml
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import base64

SECURITY_DIR = Path(__file__).parent.parent / "security"
CONFIG_DIR = Path(__file__).parent.parent / "config"

def canonicalize(data: dict) -> bytes:
    """
    Canonical JSON representation for signing.
    Sorted keys, no whitespace variance, deterministic.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")

def sign():
    config_path = CONFIG_DIR / "guardrails.yaml"
    priv_path = SECURITY_DIR / "private_key.pem"
    sig_path = CONFIG_DIR / "guardrails.yaml.sig"

    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return
    if not priv_path.exists():
        print(f"Private key not found: {priv_path}")
        print("Run: python -m Mei.scripts.generate_keys")
        return

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    
    canonical = canonicalize(config)

    priv_key = serialization.load_pem_private_key(
        priv_path.read_bytes(), password=None
    )
    
    signature = priv_key.sign(canonical)
    sig_b64 = base64.b64encode(signature).decode("ascii")

    sig_data = {
        "signature": sig_b64,
        "version": config.get("version", 0),
        "algorithm": "Ed25519",
    }
    sig_path.write_text(json.dumps(sig_data, indent=2))
    
    print(f"Signed config v{config.get('version', '?')}")
    print(f"Signature → {sig_path}")
    print(f"Canonical hash length: {len(canonical)} bytes")
if __name__ == "__main__":
    sign()
