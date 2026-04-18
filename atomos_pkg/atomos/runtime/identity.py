"""
ATOM OS v14.2 — Identity (node keys)
"""
from __future__ import annotations
import nacl.signing, nacl.encoding, nacl.hash

class IdentityManager:
    def __init__(self):
        self._keys = {}

    def generate(self, node_id: str) -> str:
        key = nacl.signing.SigningKey.generate()
        self._keys[node_id] = key
        return key.verify_key.encode(encoder=nacl.encoding.RawEncoder()).hex()

if __name__ == "__main__":
    im = IdentityManager()
    vk = im.generate("node-1")
    print(f"Identity: {vk[:16]}...")
