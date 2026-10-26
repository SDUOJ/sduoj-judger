"""Pinned debugpy 1.8.17 data-only inspection entry point.

Strict mode exposes exact builtins only. --allow-plain-fields additionally
exposes raw instance dictionaries of classes observed by __build_class__ after
installation, with an exact builtin metaclass and verified storage descriptor.
User properties, slots, subclasses of builtin containers and C extension bases
remain opaque. This prevents inspection callbacks, not debugger tampering by
hostile code in the same interpreter. The sandbox remains the security boundary.
"""

import builtins
import os
import sys
import types
import weakref

# Capture operations before the user program can replace builtins.
_TYPE, _ID, _REPR, _STR = type, id, repr, str
_INT, _FLOAT, _BOOL, _COMPLEX = int, float, bool, complex
_LIST, _TUPLE, _DICT = list, tuple, dict
_BYTES, _BYTEARRAY, _NONE = bytes, bytearray, type(None)
_OBJECT, _FRAME = object, types.FrameType
_DICT_ITEMS, _DICT_GET, _DICT_SET = dict.items, dict.get, dict.__setitem__
_LIST_LEN, _TUPLE_LEN, _DICT_LEN = list.__len__, tuple.__len__, dict.__len__
_STR_LEN, _BYTES_LEN = str.__len__, bytes.__len__
_STR_STARTS, _STR_ENDS = str.startswith, str.endswith
_INT_BITS = int.bit_length
_ENUMERATE = enumerate
_BUILD_CLASS, _WEAKREF = builtins.__build_class__, weakref.ref
_GETSET = types.GetSetDescriptorType
_GETSET_GET = types.GetSetDescriptorType.__get__
_OBJECT_GET = object.__getattribute__
_MRO_GET = type.__dict__["__mro__"].__get__
_TYPE_DICT_GET = type.__dict__["__dict__"].__get__
_PROXY_GET = types.MappingProxyType.get
_MISSING = object()
_CLASSES = {}
_ALLOW_PLAIN = False
_INSTALLED = False
_SUSPENDED = None
_MAX_CHILDREN = 100
_MAX_VISITS = 1000
_MAX_MRO = 32


def _locals_kind():
    return _TYPE(sys._getframe().f_locals)


_LOCALS_TYPE = _locals_kind()  # CPython 3.13 uses FrameLocalsProxy.
_LOCALS_ITEMS = _LOCALS_TYPE.items


def _tracked_build_class(*args, **kwargs):
    eligible = _DICT_GET(kwargs, "metaclass", _TYPE) is _TYPE
    for base in args[2:]:
        if base is not _OBJECT and (
            _TYPE(base) is not _TYPE or not _was_python_class(base)
        ):
            eligible = False
    cls = _BUILD_CLASS(*args, **kwargs)
    if eligible and _TYPE(cls) is _TYPE and _DICT_LEN(_CLASSES) < 4096:
        _DICT_SET(_CLASSES, _ID(cls), _WEAKREF(cls))
    return cls


def _was_python_class(cls):
    ref = _DICT_GET(_CLASSES, _ID(cls))
    return ref is not None and ref() is cls


def _raw_fields(value):
    """Call only an authenticated CPython-generated __dict__ storage getter."""
    if not _ALLOW_PLAIN:
        return None
    cls = _TYPE(value)
    if _TYPE(cls) is not _TYPE or not _was_python_class(cls):
        return None
    descriptor = None
    mro = _MRO_GET(cls)
    if _TUPLE_LEN(mro) > _MAX_MRO:
        return None
    for base in mro:
        if base is _OBJECT:
            continue
        # No extension/builtin base, custom metaclass, or slot-bearing class.
        if _TYPE(base) is not _TYPE or not _was_python_class(base):
            return None
        namespace = _TYPE_DICT_GET(base)
        if _PROXY_GET(namespace, "__slots__", _MISSING) is not _MISSING:
            return None
        candidate = _PROXY_GET(namespace, "__dict__", _MISSING)
        if candidate is not _MISSING:
            if (
                _TYPE(candidate) is not _GETSET
                or _OBJECT_GET(candidate, "__name__") != "__dict__"
                or _OBJECT_GET(candidate, "__objclass__") is not base
            ):
                return None
            if descriptor is None:
                descriptor = candidate
    if descriptor is None:
        return None
    raw = _GETSET_GET(descriptor, value, cls)
    return raw if _TYPE(raw) is _DICT else None


def _class_descriptor(cls, name):
    """Static namespace inspection, never getattr/hasattr on the target."""
    for base in _MRO_GET(cls):
        entry = _PROXY_GET(_TYPE_DICT_GET(base), name, _MISSING)
        if entry is _MISSING:
            continue
        for entry_base in _MRO_GET(_TYPE(entry)):
            if (
                _PROXY_GET(_TYPE_DICT_GET(entry_base), "__get__", _MISSING)
                is not _MISSING
            ):
                return True
        return False
    return False


def _visible_name(name):
    return (
        _TYPE(name) is _STR
        and not (_STR_STARTS(name, "__") and _STR_ENDS(name, "__"))
        and name != "_pydev_stop_at_break"
    )


def _dict_entries(raw, owner=None):
    entries = []
    # Iteration avoids dict lookup triggering a hostile colliding key.__eq__.
    for visited, (key, value) in _ENUMERATE(_DICT_ITEMS(raw)):
        if visited >= _MAX_VISITS:
            break
        if not _visible_name(key):
            continue
        if owner is not None and _class_descriptor(_TYPE(owner), key):
            continue
        entries.append((key, value, None))
        if _LIST_LEN(entries) >= _MAX_CHILDREN:
            break
    return entries


def _children(value):
    kind = _TYPE(value)
    if kind is _DICT:
        return _dict_entries(value)
    if kind is _LIST or kind is _TUPLE:
        entries = []
        for index, item in _ENUMERATE(value):
            if index >= _MAX_CHILDREN:
                break
            entries.append(("[" + _STR(index) + "]", item, None))
        return entries
    raw = _raw_fields(value)
    return _dict_entries(raw, value) if raw is not None else []


def _describe(value):
    kind = _TYPE(value)
    if kind is _INT:
        return "int", _REPR(value) if _INT_BITS(value) <= 4096 else "<large int>", False
    for expected, name in (
        (_BOOL, "bool"),
        (_FLOAT, "float"),
        (_COMPLEX, "complex"),
        (_NONE, "NoneType"),
    ):
        if kind is expected:
            return name, _REPR(value), False
    if kind is _STR:
        return "str", _REPR(value[:256]) + ("…" if _STR_LEN(value) > 256 else ""), False
    if kind is _BYTES:
        return (
            "bytes",
            _REPR(value[:128]) + ("…" if _BYTES_LEN(value) > 128 else ""),
            False,
        )
    if kind is _LIST:
        return "list", "<list len=" + _STR(_LIST_LEN(value)) + ">", True
    if kind is _TUPLE:
        return "tuple", "<tuple len=" + _STR(_TUPLE_LEN(value)) + ">", True
    if kind is _DICT:
        return "dict", "<dict len=" + _STR(_DICT_LEN(value)) + ">", True
    raw = _raw_fields(value)
    if raw is not None:
        return "instance", "<raw fields>", True
    return "opaque", "<opaque; inspection callbacks disabled>", False


class _SafeResolver:
    def get_contents_debug_adapter_protocol(self, value, fmt=None):
        return _children(value)

    def get_dictionary(self, value):
        return {key: val for key, val, _ in _children(value)}


_RESOLVER = _SafeResolver()


def _get_type(value):
    name, _, expandable = _describe(value)
    return _TYPE(value), name, _RESOLVER if expandable else None


def _details(value, evaluate_full_value=True, to_string=None, context=None):
    name, text, expandable = _describe(value)
    return name, "", False, _RESOLVER if expandable else None, text


def _var_data(self, fmt=None, context=None, **ignored):
    name, text, expandable = _describe(self.value)
    return {
        "name": self.name if _TYPE(self.name) is _STR else "<name>",
        "value": text,
        "type": name,
        "variablesReference": _ID(self.value) if expandable else 0,
        "presentationHint": {"attributes": ["readOnly"]},
    }


def _object_children(self, fmt=None, scope=None):
    return [
        _SUSPENDED._ObjectVariable(
            self.py_db, key, value, self._register_variable, frame=self.frame
        )
        for key, value, _ in _children(self.value)
    ]


def _frame_children(self, fmt=None, scope=None):
    if _TYPE(self.frame) is not _FRAME:
        return []
    # ScopeRequest is a debugger-owned type; never derived from the user object.
    raw = (
        self.frame.f_globals
        if scope is not None and scope.scope == "globals"
        else self.frame.f_locals
    )
    kind = _TYPE(raw)
    if kind is _DICT:
        rows = _DICT_ITEMS(raw)
    elif kind is _LOCALS_TYPE:
        rows = _LOCALS_ITEMS(raw)
    else:
        return []
    result = []
    for visited, (name, value) in _ENUMERATE(rows):
        if visited >= _MAX_VISITS:
            break
        if not _visible_name(name):
            continue
        result.append(
            _SUSPENDED._ObjectVariable(
                self.py_db, name, value, self._register_variable, frame=self.frame
            )
        )
        if _LIST_LEN(result) >= _MAX_CHILDREN:
            break
    return result


def install(*, allow_plain_fields=False):
    """Install before debugpy CLI and before executing any user module."""
    global _ALLOW_PLAIN, _INSTALLED, _SUSPENDED
    if _INSTALLED:
        _ALLOW_PLAIN = allow_plain_fields
        return
    os.environ["PYDEVD_USE_CYTHON"] = "NO"
    os.environ["PYDEVD_USE_FRAME_EVAL"] = "NO"
    import debugpy

    if debugpy.__version__ != "1.8.17":
        raise RuntimeError("Safe-inspection prototype requires debugpy==1.8.17")
    import debugpy._vendored.force_pydevd  # noqa: F401
    from _pydevd_bundle import pydevd_xml, pydevd_suspended_frames, pydevd_safe_repr

    _SUSPENDED = pydevd_suspended_frames
    old_type, old_details = pydevd_xml.get_type, pydevd_xml.get_variable_details
    pydevd_xml.get_type = _get_type
    pydevd_xml.get_variable_details = _details
    pydevd_xml.TypeResolveHandler.get_type = lambda self, value: _get_type(value)
    pydevd_xml.TypeResolveHandler._get_type = lambda self, value, *ignored: _get_type(
        value
    )
    pydevd_xml._str_from_providers = lambda *args, **kwargs: None
    pydevd_safe_repr.SafeRepr.__call__ = lambda self, value: _describe(value)[1]
    # Replace imported aliases, not only the defining module's functions.
    for module_name, module in tuple(sys.modules.items()):
        if (
            module_name.startswith(("_pydevd_bundle", "_pydev_bundle"))
            and module is not None
        ):
            namespace = module.__dict__
            for key, value in tuple(namespace.items()):
                if value is old_type:
                    namespace[key] = _get_type
                elif value is old_details:
                    namespace[key] = _details
    pydevd_suspended_frames._AbstractVariable.get_var_data = _var_data
    pydevd_suspended_frames._AbstractVariable.get_variable_reference = lambda self: _ID(
        self.value
    )
    pydevd_suspended_frames._ObjectVariable.get_children_variables = _object_children
    pydevd_suspended_frames._FrameVariable.get_children_variables = _frame_children
    _ALLOW_PLAIN = allow_plain_fields
    builtins.__build_class__ = _tracked_build_class
    _INSTALLED = True


def main():
    # Only the operator-owned leading option is ours. The same string after
    # the target script belongs to the target program's ordinary argv.
    allow_plain = _LIST_LEN(sys.argv) > 1 and sys.argv[1] == "--allow-plain-fields"
    if allow_plain:
        del sys.argv[1]
    install(allow_plain_fields=allow_plain)
    from debugpy.server import cli

    # CLI receives ordinary --listen/--wait-for-client/script arguments.
    cli.main()


if __name__ == "__main__":
    main()
