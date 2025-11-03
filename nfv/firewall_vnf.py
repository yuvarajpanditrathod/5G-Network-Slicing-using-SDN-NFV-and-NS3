#!/usr/bin/env python3
"""
Firewall VNF (AES-GCM) - Provides /encrypt and /decrypt endpoints with slice-specific encryption.

Security notes and usage guidance (non-exhaustive):
 - This VNF uses AES-GCM (AEAD) for combined encryption+authentication.
 - Recommended algorithm: AES-256-GCM (256-bit keys, 12-byte nonce, 16-byte auth tag).
 - Do NOT reuse nonces/IVs with the same key; ensure unique nonce per encryption operation.
 - Prefer using a dedicated Key Management Service (KMS) or hardware key store instead of persisting raw keys on disk.
 - If deriving keys from passphrases, use high-entropy passphrases and a unique salt per deployment; avoid fixed salts in production.
 - Hardware acceleration (AES-NI, ARM Crypto extensions) significantly improves throughput and reduces latency for AES-GCM.

Usage:
    python3 firewall_vnf.py --host 0.0.0.0 --port 9000 --bits 128

Requests (POST JSON):
    /encrypt { "data": "<base64>" } -> { "result": "<base64>" }
    /decrypt { "data": "<base64>" } -> { "result": "<base64>" }

This module contains a simple on-disk key fallback for local development (file: 'nfv_key.bin').
For production deployments (5G slicing, multi-tenant), integrate with a KMS and per-slice key separation.
"""
import argparse
import base64
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

KEY_FILE = Path("nfv_key.bin")
LOG_FORMAT = "→ %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("firewall_vnf")

SLICE_KEY_BASE = b"Slice"  # Base key for slice encryption (legacy default for developer convenience)
# NOTE: Using a fixed SALT is acceptable for local demos only. For production, use a per-deployment or per-slice unique salt
# stored and protected by your key management system. Fixed salts weaken PBKDF2-derived keys against precomputation attacks.
SALT = b"network_slicing_salt"  # LEGACY: fixed salt for key derivation (development only)


def derive_key_from_slice(bits=256):
    """Derive AES key from 'Slice' base key using PBKDF2"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=bits // 8,
        salt=SALT,
        iterations=100000,
    )
    return kdf.derive(SLICE_KEY_BASE)


def derive_key_from_passphrase(passphrase: str, bits=256):
    """Derive AES key from a passphrase using PBKDF2

    This allows providing a human-friendly passphrase (e.g., 'networkslice')
    and deriving a consistent AES key for encrypt/decrypt operations.
    """
    if not isinstance(passphrase, (bytes, bytearray)):
        passphrase = passphrase.encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=bits // 8,
        salt=SALT,
        iterations=100000,
    )
    return kdf.derive(passphrase)


def load_or_create_key(bits=256, passphrase: str = None):
    """Load AES key from file, or create/derive it.

    If `passphrase` is provided, derive a key from that passphrase and return it (do not read key file).
    If no passphrase and key file exists, load it. Otherwise derive from default slice base.
    """
    if passphrase:
        # Deriving from a passphrase is supported for developer convenience.
        # In production, prefer KMS or hardware-bound keys and avoid passphrase-derived keys when possible.
        logger.info("Deriving AES key from provided passphrase (use KMS in production)")
        return derive_key_from_passphrase(passphrase, bits=bits)

    if KEY_FILE.exists():
        data = KEY_FILE.read_bytes()
        if len(data) == (bits // 8):
            logger.info("Loading AES key from %s", KEY_FILE)
            return data
        else:
            logger.info("Found key file but length differs; re-deriving from base passphrase")

    # Derive key using the (legacy) SLICE_KEY_BASE. This is deterministic so different runs will use the same key
    # unless a passphrase or external KMS is provided. This behavior preserves compatibility with existing artifacts.
    key = derive_key_from_slice(bits=bits)
    try:
        # Try to persist locally for convenience in dev setups. This is NOT recommended for production.
        KEY_FILE.write_bytes(key)
        logger.info("Generated slice-based AES key and saved to %s (use KMS in production)", KEY_FILE)
    except Exception:
        logger.warning("Could not persist AES key to %s (permission or FS issue)", KEY_FILE)
    return key


def detect_aes_ni() -> bool:
    """Detect whether the CPU advertises AES (AES-NI) support.

    Returns True if AES instructions are present (Linux /proc/cpuinfo check), False otherwise.
    """
    try:
        if os.name == 'posix' and os.path.exists('/proc/cpuinfo'):
            with open('/proc/cpuinfo', 'r') as f:
                info = f.read()
            # 'aes' flag in x86_64 /proc/cpuinfo indicates AES-NI
            if 'aes' in info:
                return True
    except Exception:
        pass
    return False


class SliceEncryption:
    """Handles encryption/decryption of slice configurations"""
    
    def __init__(self, key):
        self.aesgcm = AESGCM(key)

    def encrypt_bytes(self, data: bytes) -> bytes:
        """Encrypt raw bytes and return nonce+ciphertext (raw bytes)."""
        nonce = os.urandom(12)
        ct = self.aesgcm.encrypt(nonce, data, None)
        return nonce + ct

    def decrypt_bytes(self, blob: bytes) -> bytes:
        """Decrypt raw nonce+ciphertext bytes and return plaintext bytes."""
        nonce = blob[:12]
        ct = blob[12:]
        return self.aesgcm.decrypt(nonce, ct, None)

    def encrypt_batch(self, blobs: list[bytes], max_workers: int = None) -> list[bytes]:
        """Encrypt a list of byte blobs in parallel and return list of nonce+ciphertext bytes.

        Uses ThreadPoolExecutor to parallelize per-message AES-GCM calls which are independent.
        This reduces per-message overhead on multi-core hosts while preserving nonce uniqueness.
        """
        if not blobs:
            return []
        results = [None] * len(blobs)
        # default to min(32, cpu_count*2) if not provided
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(self.encrypt_bytes, b): i for i, b in enumerate(blobs)}
            for fut in as_completed(futures):
                idx = futures[fut]
                results[idx] = fut.result()
        return results
    
    def encrypt_slice_config(self, slice_config):
        """Encrypt slice configuration dictionary"""
        try:
            data = json.dumps(slice_config).encode()
            nonce = os.urandom(12)
            ciphertext = self.aesgcm.encrypt(nonce, data, None)
            encrypted_data = base64.b64encode(nonce + ciphertext).decode()
            logger.info("Encrypted slice config: %s", slice_config.get('slice_name', 'unknown'))
            return encrypted_data
        except Exception as e:
            logger.error("Failed to encrypt slice config: %s", e)
            return None
    
    def decrypt_slice_config(self, encrypted_data):
        """Decrypt slice configuration and return dictionary"""
        try:
            blob = base64.b64decode(encrypted_data)
            nonce = blob[:12]
            ciphertext = blob[12:]
            plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
            slice_config = json.loads(plaintext.decode())
            logger.info("Decrypted slice config: %s", slice_config.get('slice_name', 'unknown'))
            return slice_config
        except Exception as e:
            logger.error("Failed to decrypt slice config: %s", e)
            return None
    
    def verify_slice_integrity(self, slice_config, encrypted_data):
        """Verify if decrypted data matches original slice config"""
        decrypted = self.decrypt_slice_config(encrypted_data)
        if decrypted is None:
            return False
        return decrypted == slice_config


# Global slice encryption instance
slice_encryptor = None


class Handler(BaseHTTPRequestHandler):
    def _reply_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw.decode() or "{}")
        except Exception:
            self._reply_json(400, {"error": "invalid json"})
            return

        if self.path.rstrip("/") in ("/encrypt", "/"):
            data_b64 = req.get("data")
            if not data_b64:
                self._reply_json(400, {"error": "missing data (base64)"})
                return

            try:
                blob = base64.b64decode(data_b64)
            except Exception:
                self._reply_json(400, {"error": "data must be base64-encoded"})
                return

            try:
                nonce = os.urandom(12)
                # Reuse server's SliceEncryption AESGCM instance when available to avoid per-request initialization cost
                aesgcm_inst = None
                if hasattr(self.server, 'slice_encryptor') and getattr(self.server, 'slice_encryptor') is not None:
                    aesgcm_inst = self.server.slice_encryptor.aesgcm
                if aesgcm_inst is not None:
                    ct = aesgcm_inst.encrypt(nonce, blob, None)
                else:
                    aesgcm_tmp = AESGCM(self.server.key)
                    ct = aesgcm_tmp.encrypt(nonce, blob, None)
                out = base64.b64encode(nonce + ct).decode()
                self._reply_json(200, {"result": out})
                logger.info("Encrypted %d -> %d bytes", len(blob), len(out))
            except Exception as e:
                self._reply_json(500, {"error": str(e)})
                logger.exception("Encryption failed")
            return

        if self.path.rstrip("/") == "/decrypt":
            data_b64 = req.get("data")
            if not data_b64:
                self._reply_json(400, {"error": "missing data (base64)"})
                return

            try:
                blob = base64.b64decode(data_b64)
            except Exception:
                self._reply_json(400, {"error": "data must be base64-encoded"})
                return

            try:
                nonce = blob[:12]
                ct = blob[12:]
                aesgcm_inst = None
                if hasattr(self.server, 'slice_encryptor') and getattr(self.server, 'slice_encryptor') is not None:
                    aesgcm_inst = self.server.slice_encryptor.aesgcm
                if aesgcm_inst is not None:
                    pt = aesgcm_inst.decrypt(nonce, ct, None)
                else:
                    aesgcm_tmp = AESGCM(self.server.key)
                    pt = aesgcm_tmp.decrypt(nonce, ct, None)
                out = base64.b64encode(pt).decode()
                self._reply_json(200, {"result": out})
                logger.info("Decrypted to %d bytes", len(pt))
            except Exception as e:
                self._reply_json(400, {"error": str(e)})
                logger.exception("Decryption failed")
            return

        if self.path.rstrip("/") == "/encrypt_slice":
            slice_config = req.get("slice_config")
            if not slice_config:
                self._reply_json(400, {"error": "missing slice_config"})
                return

            # Use the slice_encryptor instance for efficient encryption if available
            try:
                if hasattr(self.server, 'slice_encryptor') and getattr(self.server, 'slice_encryptor') is not None:
                    encrypted = self.server.slice_encryptor.encrypt_slice_config(slice_config)
                else:
                    encrypted = SliceEncryption(self.server.key).encrypt_slice_config(slice_config)
            except Exception:
                encrypted = None
            if encrypted:
                self._reply_json(200, {"encrypted_slice": encrypted})
            else:
                self._reply_json(500, {"error": "encryption failed"})
            return

        if self.path.rstrip("/") == "/decrypt_slice":
            encrypted_data = req.get("encrypted_data")
            if not encrypted_data:
                self._reply_json(400, {"error": "missing encrypted_data"})
                return

            try:
                if hasattr(self.server, 'slice_encryptor') and getattr(self.server, 'slice_encryptor') is not None:
                    decrypted = self.server.slice_encryptor.decrypt_slice_config(encrypted_data)
                else:
                    decrypted = SliceEncryption(self.server.key).decrypt_slice_config(encrypted_data)
            except Exception:
                decrypted = None
            if decrypted:
                self._reply_json(200, {"decrypted_slice": decrypted})
            else:
                self._reply_json(400, {"error": "decryption failed"})
            return

        if self.path.rstrip("/") == "/verify_slice":
            slice_config = req.get("slice_config")
            encrypted_data = req.get("encrypted_data")
            if not slice_config or not encrypted_data:
                self._reply_json(400, {"error": "missing slice_config or encrypted_data"})
                return

            try:
                if hasattr(self.server, 'slice_encryptor') and getattr(self.server, 'slice_encryptor') is not None:
                    verified = self.server.slice_encryptor.verify_slice_integrity(slice_config, encrypted_data)
                else:
                    verified = SliceEncryption(self.server.key).verify_slice_integrity(slice_config, encrypted_data)
            except Exception:
                verified = False
            self._reply_json(200, {"verified": verified})
            return

        self._reply_json(404, {"error": "unknown endpoint"})


def run(host="0.0.0.0", port=9000, bits=256):
    key = load_or_create_key(bits=bits)
    
    # Initialize slice encryptor
    global slice_encryptor
    slice_encryptor = SliceEncryption(key)
    
    # Check if port is already in use and find alternative
    original_port = port
    max_attempts = 10
    
    for attempt in range(max_attempts):
        try:
            server = HTTPServer((host, port), Handler)
            server.key = key
            server.slice_encryptor = slice_encryptor
            break
        except OSError as e:
            if e.errno == 98:  # Address already in use
                logger.warning(f"Port {port} is in use, trying port {port + 1}")
                port += 1
                if attempt == max_attempts - 1:
                    logger.error(f"Could not find available port after {max_attempts} attempts")
                    return
            else:
                raise e
    
    if port != original_port:
        logger.info(f"Using alternative port {port} (original {original_port} was in use)")
    # Tune server socket buffers for high-throughput encrypted traffic
    try:
        # Increase kernel socket buffers where possible (application-level)
        # Use 16 MB per-socket buffer for high-throughput encrypted traffic
        rcvbuf = 16 * 1024 * 1024
        sndbuf = 16 * 1024 * 1024
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
        # Disable Nagle for low-latency small writes
        try:
            server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        logger.info(f"Tuned server socket buffers: SO_RCVBUF={rcvbuf}, SO_SNDBUF={sndbuf}")
    except Exception as e:
        logger.warning(f"Could not tune server socket buffers: {e}")

    # Log AES-NI availability (best-effort); cryptography/OpenSSL will use hardware if available
    try:
        aes_ni = detect_aes_ni()
        logger.info(f"AES-NI detected: {aes_ni}")
        if not aes_ni:
            logger.info("If your CPU supports AES-NI, ensure OpenSSL/cryptography are using it for best performance.")
    except Exception:
        pass

    logger.info(f"Firewall VNF listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        try:
            server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Firewall VNF (AES-GCM)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--bits", type=int, default=256, choices=[128, 256])
    args = parser.parse_args()
    run(host=args.host, port=args.port, bits=args.bits)


def test_slice_encryption():
    """Test function for slice encryption/decryption"""
    print("Testing Slice Encryption/Decryption...")
    
    # Initialize encryptor
    key = load_or_create_key(bits=256)
    encryptor = SliceEncryption(key)
    
    # Sample slice configuration
    sample_slice = {
        "slice_name": "eMBB_test",
        "bandwidth": 100,
        "delay": "10ms",
        "priority": "high",
        "description": "Test eMBB slice"
    }
    
    print(f"Original slice config: {sample_slice}")
    
    # Encrypt
    encrypted = encryptor.encrypt_slice_config(sample_slice)
    print(f"Encrypted data: {encrypted}")
    
    # Decrypt
    decrypted = encryptor.decrypt_slice_config(encrypted)
    print(f"Decrypted slice config: {decrypted}")
    
    # Verify
    verified = encryptor.verify_slice_integrity(sample_slice, encrypted)
    print(f"Verification result: {verified}")
    
    return verified


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_slice_encryption()
    else:
        parser = argparse.ArgumentParser(description="Firewall VNF (AES-GCM)")
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=9000)
        parser.add_argument("--bits", type=int, default=128, choices=[128, 256])
        args = parser.parse_args()
        run(host=args.host, port=args.port, bits=args.bits)
