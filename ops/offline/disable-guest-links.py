"""Leave only loopback active inside the disposable verify guest (Linux)."""
import fcntl
import socket
import struct

GET_FLAGS = 0x8913
SET_FLAGS = 0x8914
UP = 1
LOOPBACK = 8

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
    for _, interface in socket.if_nameindex():
        request = struct.pack("16sH22x", interface.encode(), 0)
        data = fcntl.ioctl(control, GET_FLAGS, request)
        flags = struct.unpack_from("H", data, 16)[0]
        if flags & UP and not flags & LOOPBACK:
            request = struct.pack("16sH22x", interface.encode(), flags & ~UP)
            fcntl.ioctl(control, SET_FLAGS, request)
            actual = fcntl.ioctl(control, GET_FLAGS, request)
            if struct.unpack_from("H", actual, 16)[0] & UP:
                raise RuntimeError(f"Verify interface {interface} is still up")
