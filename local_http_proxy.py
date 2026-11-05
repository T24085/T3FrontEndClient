"""Shared fixed-loopback preflight for an opt-in Unreal HTTP failure request."""
import errno
import socket
from datetime import datetime,timezone


class ProxyPreflightError(RuntimeError):
    """The fixed endpoint did not positively return connection refused."""

    def __init__(self,connect_error):
        self.connect_error=connect_error
        super().__init__(f'HTTP failure endpoint did not return connection refused (error {connect_error}); no game launched')


def loopback_http_failure_preflight():
    """Observe one refusal; this does not reserve the endpoint or launch a child."""
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
        # This Windows loopback stack returns refusal after about two seconds.
        # A shorter timeout reports WSAEWOULDBLOCK, which is not proof of refusal.
        probe.settimeout(3.0)
        connection_error=probe.connect_ex(('127.0.0.1',1))
    refused_codes={errno.ECONNREFUSED,getattr(errno,'WSAECONNREFUSED',errno.ECONNREFUSED)}
    if connection_error not in refused_codes:
        raise ProxyPreflightError(connection_error)
    return {'observed_utc':datetime.now(timezone.utc).isoformat(),'connect_error':connection_error,
        'connection_refused':True,'semantics':'Point observation only; the endpoint is not reserved. Native request failures still require verification.'}
