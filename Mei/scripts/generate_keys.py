"""
One-time script: Generate Ed25519 key pair for guardrails signing.
"""

from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

SECURITY_DIR = Path(__file__).parent.parent/"security"

def generate():
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)

    private_key= Ed25519PrivateKey.generate()

    priv_path = SECURITY_DIR/"private_key.pem"
    priv_bytes= private_key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
                                          encryption_algorithm=serialization.NoEncryption())

    priv_path.write_bytes(priv_bytes)
    print(f"Private key → {priv_path}")

    pub_path = SECURITY_DIR / "public_key.pem"
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path.write_bytes(pub_bytes)
    print(f"Public key  → {pub_path}")
if __name__ == "__main__":
    generate()
