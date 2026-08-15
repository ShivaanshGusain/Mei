"""
Secure guardrails loader.
Verifies Ed25519 signature + rollback protection before trusting config.
"""

import json
import yaml
import base64
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

SECURITY_DIR = Path(__file__).parent
CONFIG_DIR   = Path(__file__).parent.parent / "config"
VERSION_FILE = SECURITY_DIR / ".latest_version"

def _canonicalize(data: dict) -> bytes:
    """Same canonical form used by the signing script."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")

def _load_public_key() -> Ed25519PublicKey:
    """Load the embedded public key."""
    pub_path = SECURITY_DIR / "public_key.pem"
    if not pub_path.exists():
        raise FileNotFoundError(
            f"Public key not found at {pub_path}. "
            f"Run: python -m Mei.scripts.generate_keys"
        )
    return serialization.load_pem_public_key(pub_path.read_bytes())


def _get_last_version() -> int:
    """Read the last successfully loaded config version."""
    try:
        return int(VERSION_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0

def _set_last_version(version: int) -> None:
    """Persist the version counter."""
    VERSION_FILE.write_text(str(version))
    
def load_and_verify() -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Load and verify the guardrails config.
    
    Returns:
        (success, config_dict_or_None, reason_string)
    
    On ANY failure, returns (False, None, reason).
    Caller MUST fall back to hardcoded minimal-safe defaults.
    """
    config_path = CONFIG_DIR / "guardrails.yaml"
    sig_path = CONFIG_DIR / "guardrails.yaml.sig"
    
    if not config_path.exists():
        return (False, None, f"Config not found: {config_path}")
    if not sig_path.exists():
        return (False, None, f"Signature not found: {sig_path}")
    
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        
        if not isinstance(config, dict):
            return (False, None, "Config is not a valid YAML mapping")
        
        sig_data = json.loads(sig_path.read_text())
        sig_b64 = sig_data.get("signature")
        if not sig_b64:
            return (False, None, "Signature file missing 'signature' field")
        
        signature = base64.b64decode(sig_b64)
        
        public_key = _load_public_key()
        canonical = _canonicalize(config)
        
        try:
            public_key.verify(signature, canonical)
        except InvalidSignature:
            return (False, None, "SIGNATURE VERIFICATION FAILED — "
                                 "config has been tampered with")
        
        config_version = config.get("version", 0)
        last_version = _get_last_version()
        
        if config_version < last_version:
            return (False, None,
                    f"ROLLBACK DETECTED: config version {config_version} "
                    f"< last seen {last_version}")
        
        _set_last_version(config_version)
        return (True, config, f"Verified config v{config_version}")
        
    except Exception as e:
        return (False, None, f"Load/verify error: {e}")