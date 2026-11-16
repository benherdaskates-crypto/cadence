# PyInstaller runtime hook (built exe only).
# The shared .exe leaves out OpenSSL (~2.7 MB) so it fits Discord's 10 MB limit.
# pywebview imports `ssl` at module level for an HTTPS server option Cadence
# never uses, so provide a clearly-marked placeholder. Nothing in Cadence makes
# HTTPS calls through Python: update checks use Windows' .NET HTTPS (updater.py).
import sys
import types

try:
    import ssl  # noqa: F401
except ImportError:
    _stub = types.ModuleType("ssl")
    _stub.CADENCE_STUB = True

    class SSLContext:  # noqa: D401
        def __init__(self, *args, **kwargs):
            raise RuntimeError("TLS isn't bundled in this build of Cadence.")

    def _unavailable(*args, **kwargs):
        raise RuntimeError("TLS isn't bundled in this build of Cadence.")

    _stub.SSLContext = SSLContext
    _stub.create_default_context = _unavailable
    _stub._create_default_https_context = _unavailable
    _stub.PROTOCOL_TLS_SERVER = 17
    _stub.HAS_SNI = False
    sys.modules["ssl"] = _stub
