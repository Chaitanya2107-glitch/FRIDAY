"""Exercise the D-Bus decoder and setup boundaries without loading native DLLs."""

import ctypes as C

import pytest

from services.phone import transport


class IteratorLib:
    def __init__(self, iterator, node):
        self.positions = {C.addressof(iterator): ([node], 0)}
        self.strings = []

    def at(self, pointer):
        nodes, index = self.positions[C.addressof(pointer._obj)]
        return nodes[index] if index < len(nodes) else ("\x00", None)

    def dbus_message_iter_get_arg_type(self, pointer):
        return ord(self.at(pointer)[0])

    def dbus_message_iter_get_basic(self, pointer, output):
        kind, value = self.at(pointer)
        if kind in "sog":
            self.strings.append(value.encode())
            C.cast(output, C.POINTER(C.c_char_p))[0] = self.strings[-1]
        else:
            C.cast(output, C.POINTER(C.c_int32))[0] = value

    def dbus_message_iter_recurse(self, pointer, child):
        self.positions[C.addressof(child._obj)] = (self.at(pointer)[1], 0)

    def dbus_message_iter_next(self, pointer):
        address = C.addressof(pointer._obj)
        nodes, index = self.positions[address]
        self.positions[address] = nodes, index + 1
        return index + 1 < len(nodes)


def decode(node):
    iterator = transport._Iter()
    bus = transport.Transport()
    bus.lib = IteratorLib(iterator, node)
    return bus._value(iterator)


def test_public_iterator_abi_and_getall_variant_dictionary():
    assert C.sizeof(transport._Iter) == (72 if C.sizeof(C.c_void_p) == 8 else 56)
    def entry(key, value):
        return "e", [("s", key), ("v", [value])]
    value = decode(("a", [entry("name", ("s", "Android")), entry("isPaired", ("b", 1)),
                          entry("pairState", ("i", 2)), entry("count", ("u", 3)),
                          entry("supportedPlugins", ("a", [("s", "notifications"), ("s", "findmyphone")]))]))
    assert value == {"name": "Android", "isPaired": True, "pairState": 2, "count": 3,
                     "supportedPlugins": ["notifications", "findmyphone"]}


def test_decoder_rejects_oversized_unknown_and_deep_responses():
    for node in (("s", "x" * 8193), ("a", [("s", "x")] * 129), ("x", 1)):
        with pytest.raises(transport.PhoneError):
            decode(node)
    node = "s", "nested"
    for _ in range(8):
        node = "v", [node]
    with pytest.raises(transport.PhoneError):
        decode(node)


@pytest.mark.parametrize("address", ["tcp:host=evil.example,port=1234", "autolaunch:;tcp:host=evil.example",
                                     "autolaunch:scope=other", "unix:path=/remote/socket",
                                     "tcp:host=127.0.0.1,host=evil.example,port=1234"])
def test_phone_bus_cannot_be_redirected_to_a_remote_or_different_bus(monkeypatch, tmp_path, address):
    monkeypatch.setattr(transport, "installation", lambda: tmp_path / "kdeconnect-cli.exe")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    with pytest.raises(transport.PhoneError, match="local session bus"):
        transport.Transport().__enter__()


def test_dll_directory_failure_becomes_local_setup_error(monkeypatch, tmp_path):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setattr(transport, "installation", lambda: tmp_path / "kdeconnect-cli.exe")
    (tmp_path / "dbus-1-3.dll").touch()
    def denied(_):
        raise OSError("no access")
    monkeypatch.setattr(transport.os, "add_dll_directory", denied)
    with pytest.raises(transport.PhoneError, match="Couldn't load"):
        transport.Transport().__enter__()
