"""Region (.mca) 文件：定位 chunk、解压、校验头部、隔离坏 chunk。

格式：头部 8KB = 1024 个位置条目（4 字节：3 字节起始扇区 + 1 字节扇区数）
                + 1024 个时间戳（4 字节）。
每个 chunk：4 字节长度（含压缩类型那一字节）+ 1 字节压缩类型 + 数据。
压缩类型：1 gzip / 2 zlib / 3 不压缩。
"""
from __future__ import annotations

import gzip
import os
import struct
import zlib
from dataclasses import dataclass

SECTOR = 4096
ENTRIES = 1024


class RegionError(Exception):
    """region 文件结构不对：截断、长度字段异常、未知压缩类型。"""


@dataclass
class ChunkEntry:
    index: int
    cx: int
    cz: int
    offset: int          # 起始扇区号
    sectors: int         # 占几个扇区
    timestamp: int

    @property
    def present(self):
        return self.offset > 0 and self.sectors > 0

    @property
    def byte_offset(self):
        return self.offset * SECTOR


class RegionFile:
    def __init__(self, path):
        self.path = path
        self.size = os.path.getsize(path)
        with open(path, "rb") as f:
            self.header = f.read(SECTOR * 2)
        base = os.path.basename(path)
        try:
            parts = base.split(".")
            self.rx, self.rz = int(parts[1]), int(parts[2])
        except (IndexError, ValueError):
            self.rx = self.rz = 0
        self.entries = self._parse()

    def _parse(self):
        out = []
        for i in range(ENTRIES):
            loc = self.header[i * 4:i * 4 + 4]
            ts_raw = self.header[SECTOR + i * 4:SECTOR + i * 4 + 4]
            offset = int.from_bytes(loc[:3], "big")
            count = loc[3]
            ts = int.from_bytes(ts_raw, "big") if len(ts_raw) == 4 else 0
            out.append(ChunkEntry(
                index=i,
                cx=self.rx * 32 + (i % 32),
                cz=self.rz * 32 + (i // 32),
                offset=offset,
                sectors=count,
                timestamp=ts,
            ))
        return out

    def chunks(self):
        return [e for e in self.entries if e.present]

    def header_issues(self):
        """头部自检：越界、扇区重叠、被截断。"""
        issues = []
        used = []
        for e in self.chunks():
            if e.offset <= 1:
                issues.append(f"chunk ({e.cx},{e.cz}) 指向头部区域（扇区 {e.offset}）")
                continue
            if e.byte_offset + 4 > self.size:
                issues.append(f"chunk ({e.cx},{e.cz}) 偏移越界：扇区 {e.offset} 超出文件末尾")
                continue
            if e.byte_offset + e.sectors * SECTOR > self.size:
                issues.append(
                    f"chunk ({e.cx},{e.cz}) 声明 {e.sectors} 个扇区，超出文件末尾（文件被截断？）"
                )
            used.append(e)
        used.sort(key=lambda e: e.offset)
        for a, b in zip(used, used[1:]):
            if a.offset + a.sectors > b.offset:
                issues.append(f"扇区重叠：chunk ({a.cx},{a.cz}) 与 ({b.cx},{b.cz})")
        return issues

    def read_payload(self, entry):
        """返回「长度字段之后」的原始数据 = 压缩类型字节 + 压缩数据。"""
        with open(self.path, "rb") as f:
            f.seek(entry.byte_offset)
            head = f.read(4)
            if len(head) < 4:
                raise RegionError("读长度字段失败（文件截断）")
            length = struct.unpack(">I", head)[0]
            if length < 1:
                raise RegionError(f"长度字段异常：{length}")
            body = f.read(length)
        if len(body) < length:
            raise RegionError(f"数据被截断：声明 {length} 字节，只读到 {len(body)}")
        return body

    def read_nbt_bytes(self, entry):
        body = self.read_payload(entry)
        comp = body[0]
        payload = body[1:]
        try:
            if comp == 1:
                return gzip.decompress(payload)
            if comp == 2:
                return zlib.decompress(payload)
            if comp == 3:
                return payload
        except (OSError, zlib.error) as exc:
            raise RegionError(f"解压失败（类型 {comp}）：{exc}") from exc
        raise RegionError(f"未知压缩类型 {comp}")

    def isolate(self, entry):
        """把这个 chunk 从头部指针里摘掉；数据还留在文件里，只是不再被引用。

        这是修「单个 chunk 坏了导致整个世界打不开」的标准做法：坏的丢掉，
        别的地方照常加载。调用方负责先备份整个 .mca。
        """
        header = bytearray(self.header)
        header[entry.index * 4:entry.index * 4 + 4] = b"\x00\x00\x00\x00"
        with open(self.path, "r+b") as f:
            f.seek(0)
            f.write(bytes(header))
            f.flush()
            os.fsync(f.fileno())
        self.header = bytes(header)
        self.entries = self._parse()
