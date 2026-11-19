"""最小 NBT 读写实现（大端），只依赖标准库。

读：解析 level.dat / 玩家 .dat / region 里的 chunk。
写：只给测试造夹具和修复工具用（写出是显式类型，Python 原生 int 分不出 Byte/Short/Int/Long）。
"""
from __future__ import annotations

import gzip
import struct
import zlib

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

MAX_DEPTH = 512          # 防止恶意/损坏文件把栈打爆
MAX_LIST = 8_000_000     # 同上，防止长度字段造假


class NbtError(ValueError):
    """NBT 结构不合法：截断、未知 tag、层数过深。"""


# ---------------------------------------------------------------- 写出用的类型包装
class _Tagged:
    tag = None

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"{type(self).__name__}({self.value!r})"


class Byte(_Tagged):
    tag = TAG_BYTE


class Short(_Tagged):
    tag = TAG_SHORT


class Int(_Tagged):
    tag = TAG_INT


class Long(_Tagged):
    tag = TAG_LONG


class Float(_Tagged):
    tag = TAG_FLOAT


class Double(_Tagged):
    tag = TAG_DOUBLE


class String(_Tagged):
    tag = TAG_STRING


class ByteArray(_Tagged):
    tag = TAG_BYTE_ARRAY


class IntArray(_Tagged):
    tag = TAG_INT_ARRAY


class LongArray(_Tagged):
    tag = TAG_LONG_ARRAY


# ---------------------------------------------------------------- 读
class _Reader:
    def __init__(self, buf):
        self.b = buf
        self.i = 0
        self.n = len(buf)

    def take(self, n):
        if self.i + n > self.n:
            raise NbtError(f"数据被截断：还需要 {n} 字节，只剩 {self.n - self.i}")
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def num(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self):
        n = self.num(">H")
        return self.take(n).decode("utf-8", "replace")

    def payload(self, tag, depth=0):
        if depth > MAX_DEPTH:
            raise NbtError("NBT 层数过深（文件损坏？）")
        if tag == TAG_BYTE:
            return self.num(">b")
        if tag == TAG_SHORT:
            return self.num(">h")
        if tag == TAG_INT:
            return self.num(">i")
        if tag == TAG_LONG:
            return self.num(">q")
        if tag == TAG_FLOAT:
            return self.num(">f")
        if tag == TAG_DOUBLE:
            return self.num(">d")
        if tag == TAG_BYTE_ARRAY:
            n = self.num(">i")
            if n < 0 or n > MAX_LIST:
                raise NbtError(f"ByteArray 长度异常：{n}")
            return list(self.take(n))
        if tag == TAG_STRING:
            return self.string()
        if tag == TAG_LIST:
            et = self.num(">b")
            n = self.num(">i")
            if n < 0 or n > MAX_LIST:
                raise NbtError(f"List 长度异常：{n}")
            return [self.payload(et, depth + 1) for _ in range(n)]
        if tag == TAG_COMPOUND:
            d = {}
            while True:
                tt = self.num(">b")
                if tt == TAG_END:
                    return d
                if tt < 0 or tt > TAG_LONG_ARRAY:
                    raise NbtError(f"未知 tag 类型 {tt}")
                name = self.string()
                d[name] = self.payload(tt, depth + 1)
        if tag == TAG_INT_ARRAY:
            n = self.num(">i")
            if n < 0 or n > MAX_LIST:
                raise NbtError(f"IntArray 长度异常：{n}")
            return list(struct.unpack(">%di" % n, self.take(4 * n)))
        if tag == TAG_LONG_ARRAY:
            n = self.num(">i")
            if n < 0 or n > MAX_LIST:
                raise NbtError(f"LongArray 长度异常：{n}")
            return list(struct.unpack(">%dq" % n, self.take(8 * n)))
        raise NbtError(f"未知 tag 类型 {tag}")


def parse(buf):
    """bytes -> (根名字, payload)。根是 compound 时 payload 是 dict。"""
    r = _Reader(buf)
    tag = r.num(">b")
    if tag == TAG_END:
        return "", None
    if tag < 0 or tag > TAG_LONG_ARRAY:
        raise NbtError(f"未知根 tag 类型 {tag}")
    name = r.string()
    return name, r.payload(tag)


def load_bytes(raw):
    """自动识别 gzip / zlib / 未压缩三种外层。"""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif raw[:1] == b"\x78":
        raw = zlib.decompress(raw)
    return parse(raw)


def load(path):
    with open(path, "rb") as f:
        return load_bytes(f.read())


def load_payload(path):
    """只要 payload，根名字丢掉（level.dat / 玩家 dat 都用得上）。"""
    return load(path)[1]


def unwrap_data(payload):
    """level.dat 外面包了一层 Data；玩家的 .dat 没有。"""
    if isinstance(payload, dict) and isinstance(payload.get("Data"), dict):
        return payload["Data"]
    return payload


# ---------------------------------------------------------------- 写
def _infer(value):
    if isinstance(value, _Tagged):
        return value.tag
    if isinstance(value, bool):
        return TAG_BYTE
    if isinstance(value, int):
        return TAG_INT
    if isinstance(value, float):
        return TAG_DOUBLE
    if isinstance(value, str):
        return TAG_STRING
    if isinstance(value, dict):
        return TAG_COMPOUND
    if isinstance(value, (list, tuple)):
        return TAG_LIST
    if isinstance(value, (bytes, bytearray)):
        return TAG_BYTE_ARRAY
    raise TypeError(f"写不出这个类型：{type(value).__name__}")


def _raw(value):
    if isinstance(value, _Tagged):
        return value.value
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _string_bytes(s):
    b = s.encode("utf-8")
    if len(b) > 65535:
        raise ValueError("字符串太长")
    return struct.pack(">H", len(b)) + b


def _payload_bytes(tag, value, depth=0):
    if depth > MAX_DEPTH:
        raise NbtError("层数过深")
    v = _raw(value)
    if tag == TAG_BYTE:
        return struct.pack(">b", int(v))
    if tag == TAG_SHORT:
        return struct.pack(">h", int(v))
    if tag == TAG_INT:
        return struct.pack(">i", int(v))
    if tag == TAG_LONG:
        return struct.pack(">q", int(v))
    if tag == TAG_FLOAT:
        return struct.pack(">f", float(v))
    if tag == TAG_DOUBLE:
        return struct.pack(">d", float(v))
    if tag == TAG_BYTE_ARRAY:
        return struct.pack(">i", len(v)) + bytes(v)
    if tag == TAG_STRING:
        return _string_bytes(v)
    if tag == TAG_LIST:
        items = list(v)
        et = _infer(items[0]) if items else TAG_END
        for item in items:
            if _infer(item) != et:
                raise TypeError("NBT 列表里类型不一致")
        out = struct.pack(">bi", et, len(items))
        return out + b"".join(_payload_bytes(et, i, depth + 1) for i in items)
    if tag == TAG_COMPOUND:
        out = bytearray()
        for key, item in v.items():
            t = _infer(item)
            out.append(t)
            out += _string_bytes(key)
            out += _payload_bytes(t, item, depth + 1)
        out.append(TAG_END)
        return bytes(out)
    if tag == TAG_INT_ARRAY:
        return struct.pack(">i", len(v)) + struct.pack(">%di" % len(v), *[int(x) for x in v])
    if tag == TAG_LONG_ARRAY:
        return struct.pack(">i", len(v)) + struct.pack(">%dq" % len(v), *[int(x) for x in v])
    raise NbtError(f"未知 tag 类型 {tag}")


def dumps(root_name, payload, compress=True):
    """按 MC 的习惯存成 gzip（level.dat / 玩家 dat / region chunk 都是这样）。"""
    body = bytes([TAG_COMPOUND]) + _string_bytes(root_name) + _payload_bytes(TAG_COMPOUND, payload)
    return gzip.compress(body, 6) if compress else body


def save(path, root_name, payload, compress=True):
    with open(path, "wb") as f:
        f.write(dumps(root_name, payload, compress=compress))
