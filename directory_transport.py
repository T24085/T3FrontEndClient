
"""Bounded HTTPS transport for the public discovery service."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import http.client
import socket
import ssl
import time
from urllib.parse import urlsplit

from server_directory import (DIRECTORY_PATH, HEARTBEAT_PATH, MAX_RESPONSE, DirectoryError,
                              canonical, master_url, public_address, read_json)


class PublicHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, port, address=None, *, timeout=4):
        super().__init__(hostname, port, timeout=timeout, context=ssl.create_default_context())
        self.address = public_address(address) if address is not None else None

    def connect(self):
        if self.address is None:
            candidates = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
            for _, _, _, _, endpoint in candidates:
                try:
                    self.address = public_address(endpoint[0])
                    break
                except DirectoryError:
                    continue
            if self.address is None:
                raise DirectoryError('Directory master has no public IPv4 address.')
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def directory_request(origin, document=None):
    target = urlsplit(master_url(origin))
    publishing = document is not None
    connection = PublicHTTPS(target.hostname, target.port or 443)
    try:
        connection.request('POST' if publishing else 'GET', HEARTBEAT_PATH if publishing else DIRECTORY_PATH,
                           body=canonical(document) if publishing else None,
                           headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != (202 if publishing else 200):
            raise DirectoryError(f'Directory master returned HTTP {response.status}.')
        if publishing:
            return None
        if response.headers.get_content_type() != 'application/json':
            raise DirectoryError('Directory master returned invalid content.')
        stream = response.fp.raw
        deadline = time.monotonic() + 8
        raw = bytearray()
        while len(raw) <= MAX_RESPONSE and not response.isclosed():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DirectoryError('Directory master response timed out.')
            stream._sock.settimeout(min(remaining, 4))
            more = response.read1(min(65536, MAX_RESPONSE + 1 - len(raw)))
            if not more:
                break
            raw.extend(more)
        return read_json(bytes(raw))
    finally:
        connection.close()


def request_masters(origins, document=None, *, fetch=directory_request):
    """A slow or invalid master cannot suppress a valid result from another."""
    unique = tuple(dict.fromkeys(master_url(origin) for origin in origins))
    if not unique:
        return
    with ThreadPoolExecutor(max_workers=len(unique), thread_name_prefix='directory') as pool:
        pending = {pool.submit(fetch, origin, document): origin for origin in unique}
        for result in as_completed(pending):
            origin = pending[result]
            try:
                yield origin, result.result()
            except (DirectoryError, OSError, http.client.HTTPException):
                continue


def measure_ping(row):
    """Measure TLS latency to a selected published host directly from Starter."""
    start = time.monotonic()
    connection = PublicHTTPS(row['hostname'], row['port'], row['address'], timeout=3)
    try:
        connection.connect()
        return round((time.monotonic() - start) * 1000)
    finally:
        connection.close()
