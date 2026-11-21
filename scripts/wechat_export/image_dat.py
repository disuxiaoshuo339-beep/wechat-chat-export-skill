from __future__ import annotations

import ctypes
import hashlib
import re
from collections import Counter
from pathlib import Path

from Cryptodome.Cipher import AES

from .key_scan import (
    PROCESS_QUERY_INFORMATION,
    PROCESS_VM_READ,
    _kernel32,
    enumerate_authorized_weixin_processes,
    iter_readable_regions,
)

# 微信 4.x 图片 .dat：15 字节头（6 字节签名 + AES 段明文长度 + XOR 段长度 + 1 字节），
# 后面依次是 AES-128-ECB 段、未加密段、单字节 XOR 段。
# V1 用固定密钥；V2 的密钥在微信进程内存里，只在内存里用，不落盘。

V1_SIGNATURE = b"\x07\x08V1\x08\x07"
V2_SIGNATURE = b"\x07\x08V2\x08\x07"
V1_KEY = b"cfcd208495d565ef"
HEADER_SIZE = 15

_MAGICS = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG", ".png"),
    (b"GIF8", ".gif"),
    (b"wxgf", ".wxgf"),
    (b"RIFF", ".webp"),
    (b"II*\x00", ".tif"),
    (b"MM\x00*", ".tif"),
)

_KEY_RUN = re.compile(
    rb"(?<![0-9A-Za-z])[0-9A-Za-z]{16}(?:[0-9A-Za-z]{16})?(?![0-9A-Za-z])"
)
_CHUNK = 4 * 1024 * 1024


def image_ext(data: bytes) -> str | None:
    for magic, ext in _MAGICS:
        if data.startswith(magic):
            return ext
    return None


def is_v2(data: bytes) -> bool:
    return data[:6] == V2_SIGNATURE


def _aes_cipher_len(plain_len: int) -> int:
    return plain_len // 16 * 16 + 16  # PKCS7：整块时再补一块


def aes_sample(data: bytes) -> bytes | None:
    """V2 文件 AES 段的第一块密文，用来验证候选密钥。"""
    if not is_v2(data) or len(data) < HEADER_SIZE + 16:
        return None
    return data[HEADER_SIZE : HEADER_SIZE + 16]


def decrypt_dat(data: bytes, aes_key: bytes | None, xor_key: int | None) -> bytes:
    signature = data[:6]
    if signature in (V1_SIGNATURE, V2_SIGNATURE):
        key = V1_KEY if signature == V1_SIGNATURE else aes_key
        if key is None:
            raise ValueError("缺少图片 AES 密钥")
        aes_size = int.from_bytes(data[6:10], "little")
        xor_size = int.from_bytes(data[10:14], "little")
        body = data[HEADER_SIZE:]
        cipher_len = min(_aes_cipher_len(aes_size), len(body) // 16 * 16) if aes_size else 0
        head = AES.new(key, AES.MODE_ECB).decrypt(body[:cipher_len])[:aes_size]
        rest = body[cipher_len:]
        xor_size = min(xor_size, len(rest))
        middle, tail = rest[: len(rest) - xor_size], rest[len(rest) - xor_size :]
        if tail:
            if xor_key is None:
                raise ValueError("缺少图片 XOR 密钥")
            tail = tail.translate(bytes(value ^ xor_key for value in range(256)))
        return head + middle + tail
    # 更老的格式：整文件单字节 XOR，按文件头魔数反推
    for magic, _ in _MAGICS:
        key_byte = data[0] ^ magic[0]
        if all(data[index] ^ key_byte == magic[index] for index in range(len(magic))):
            return data.translate(bytes(value ^ key_byte for value in range(256)))
    raise ValueError("无法识别的 .dat 格式")


def find_xor_key(dat_files: list[Path]) -> int | None:
    """JPEG 以 FF D9 结尾：V2 文件末两字节异或同一个值能还原出 FF D9，就是 XOR 密钥。多文件投票。"""
    votes: Counter[int] = Counter()
    for path in dat_files:
        data = path.read_bytes()
        if not is_v2(data) or int.from_bytes(data[10:14], "little") < 2:
            continue
        key = data[-1] ^ 0xD9
        if data[-2] ^ key == 0xFF:
            votes[key] += 1
    return votes.most_common(1)[0][0] if votes else None


def _valid_key(candidate: bytes, samples: list[bytes]) -> bool:
    cipher = AES.new(candidate, AES.MODE_ECB)
    return all(image_ext(cipher.decrypt(sample)) for sample in samples)


def derive_aes_key(account_id: str, samples: list[bytes], xwechat_config: Path) -> bytes | None:
    """V2 密钥 = MD5(str(uin) + 微信号) 的前 16 个十六进制字符；uin 在
    %APPDATA%\\Tencent\\xwechat 下各 kvcomm 目录的文件名里（key_<uin>_… 等）。
    逐个候选验证，不用读进程内存。已在微信 4.2.0.13 上验证。"""
    if not samples or not xwechat_config.is_dir():
        return None
    wxid = re.sub(r"_[0-9a-f]{4}$", "", account_id)
    uins: set[str] = set()
    for path in xwechat_config.rglob("kvcomm/*"):
        match = re.match(r"(?:key|reportnow|monitordata)_(\d+)_", path.name)
        if match:
            uins.add(match.group(1))
    for uin in sorted(uins):
        candidate = hashlib.md5((uin + wxid).encode("utf-8")).hexdigest()[:16].encode("ascii")
        if _valid_key(candidate, samples):
            return candidate
    return None


def find_aes_key(samples: list[bytes]) -> bytes | None:
    """在运行中的微信进程内存里找 V2 图片密钥：16 或 32 位字母数字串的前 16 字节，
    能把每个样本的首块解成图片文件头才算数。只读内存，不写、不注入。"""
    if not samples:
        return None
    kernel32 = _kernel32()
    tried: set[bytes] = set()
    for process in enumerate_authorized_weixin_processes():
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, process.pid
        )
        if not handle:
            continue
        try:
            for base, size in iter_readable_regions(handle):
                offset = 0
                carry = b""
                while offset < size:
                    requested = min(_CHUNK, size - offset)
                    buffer = ctypes.create_string_buffer(requested)
                    read = ctypes.c_size_t()
                    ok = kernel32.ReadProcessMemory(
                        handle,
                        ctypes.c_void_p(base + offset),
                        buffer,
                        requested,
                        ctypes.byref(read),
                    )
                    if ok and read.value:
                        data = carry + buffer.raw[: read.value]
                        for match in _KEY_RUN.finditer(data):
                            candidate = match.group()[:16]
                            if candidate in tried:
                                continue
                            tried.add(candidate)
                            if _valid_key(candidate, samples):
                                return candidate
                        carry = data[-33:]
                    else:
                        carry = b""
                    offset += requested
        finally:
            kernel32.CloseHandle(handle)
    return None
