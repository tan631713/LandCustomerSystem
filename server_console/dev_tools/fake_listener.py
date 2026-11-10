"""Dev/test only: a throw-away HTTPS listener on 127.0.0.1:8732 with a
self-signed certificate, so the console's "port 8732 answers a TLS
handshake" check sees a running server while screenshots are taken.
Prints a uvicorn-style 'Started server process' line like the real thing.
"""

import datetime
import os
import socket
import ssl
import sys
import tempfile
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake-home-server")])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (
    x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256())
)
directory = tempfile.mkdtemp()
cert_path, key_path = os.path.join(directory, "c.pem"), os.path.join(directory, "k.pem")
open(cert_path, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
open(key_path, "wb").write(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(cert_path, key_path)

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", 8732))
server.listen(8)
print(f"INFO:     Started server process [{os.getpid()}]", flush=True)
while True:
    connection, _address = server.accept()
    try:
        context.wrap_socket(connection, server_side=True).close()
    except (ssl.SSLError, OSError):
        connection.close()
