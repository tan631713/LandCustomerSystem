"""Compatibility helpers for openpyxl optional NumPy integration."""


def ensure_openpyxl_numpy_compat():
    """Patch missing NumPy aliases before importing openpyxl.

    openpyxl 3.1.x optionally imports NumPy and references aliases such as
    ``numpy.short``. Some packaged environments can expose a NumPy module where
    one or more of those aliases are missing, which makes Excel import/export
    fail before the workbook is even opened. Missing aliases are only used for
    type checks, so mapping them to their closest available type is safe.
    """
    try:
        import numpy
    except Exception:
        return

    required_types = {
        "int8": int,
        "int16": int,
        "int32": int,
        "int64": int,
        "uint8": int,
        "uint16": int,
        "uint32": int,
        "uint64": int,
        "float16": float,
        "float32": float,
        "float64": float,
        "bool": bool,
    }
    for missing_name, final_fallback in required_types.items():
        if not hasattr(numpy, missing_name):
            setattr(numpy, missing_name, final_fallback)

    aliases = {
        "short": ("int16", int),
        "ushort": ("uint16", int),
        "intc": ("int32", int),
        "uintc": ("uint32", int),
        "int_": ("int64", int),
        "uint": ("uint64", int),
        "longlong": ("int64", int),
        "ulonglong": ("uint64", int),
        "half": ("float16", float),
        "single": ("float32", float),
        "double": ("float64", float),
        "longdouble": ("float64", float),
        "intp": ("int64", int),
        "uintp": ("uint64", int),
        "bool_": ("bool", bool),
        "floating": ("float64", float),
        "integer": ("int64", int),
    }
    for missing_name, (fallback_name, final_fallback) in aliases.items():
        if hasattr(numpy, missing_name):
            continue
        setattr(numpy, missing_name, getattr(numpy, fallback_name, final_fallback))
