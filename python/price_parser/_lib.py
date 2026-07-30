"""ctypes bindings for the Mojo price extraction kernels."""

from __future__ import annotations

import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_PATH = os.environ.get(
    "MOJO_PRICE_PARSER_LIB",
    os.path.join(ROOT, "dist", "libmojo-price-parser.so"),
)

I = ctypes.c_int64
P = ctypes.c_void_p
_SIGNATURES = {
    "mpp_extract_one": ([P, I, P], I),
    "mpp_extract_many": ([P, I, P, I, P, P], I),
}

_LIB: ctypes.CDLL | None = None
_PY_BYTES_AS_STRING = ctypes.pythonapi.PyBytes_AsString
_PY_BYTES_AS_STRING.argtypes = [ctypes.py_object]
_PY_BYTES_AS_STRING.restype = ctypes.c_void_p


def lib() -> ctypes.CDLL:
    global _LIB
    if _LIB is None:
        if not os.path.exists(LIB_PATH):
            raise RuntimeError(
                f"Mojo library not found at {LIB_PATH}; run `pixi run build` first"
            )
        _LIB = ctypes.CDLL(LIB_PATH)
        for name, (argtypes, restype) in _SIGNATURES.items():
            fn = getattr(_LIB, name)
            fn.argtypes = argtypes
            fn.restype = restype
    return _LIB


def address(value: ctypes.Array[ctypes._CData]) -> int:
    return ctypes.addressof(value)


def bytes_address(value: bytes) -> int:
    result = _PY_BYTES_AS_STRING(value)
    if result is None:
        raise RuntimeError("unable to access bytes buffer")
    return result
