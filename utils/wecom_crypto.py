"""
企业微信回调加解密工具（兼容安全模式）
"""
import base64
import hashlib
import os
import random
import socket
import string
import struct
from typing import Tuple
from xml.etree import ElementTree as ET

from Crypto.Cipher import AES


class WeComCryptoError(Exception):
    pass


class PKCS7Encoder:
    block_size = 32

    @classmethod
    def encode(cls, text: bytes) -> bytes:
        amount_to_pad = cls.block_size - (len(text) % cls.block_size)
        if amount_to_pad == 0:
            amount_to_pad = cls.block_size
        pad = bytes([amount_to_pad])
        return text + pad * amount_to_pad

    @classmethod
    def decode(cls, text: bytes) -> bytes:
        pad = text[-1]
        if pad < 1 or pad > cls.block_size:
            raise WeComCryptoError("invalid pkcs7 padding")
        return text[:-pad]


def _sha1(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    arr = [token, timestamp, nonce, encrypt]
    arr.sort()
    s = "".join(arr)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _gen_random_str(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        if not token or not encoding_aes_key or not corp_id:
            raise WeComCryptoError("wecom crypto config missing")
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        self.iv = self.aes_key[:16]

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        return _sha1(self.token, timestamp, nonce, encrypt) == msg_signature

    def decrypt(self, encrypt: str) -> str:
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        plain = cipher.decrypt(base64.b64decode(encrypt))
        plain = PKCS7Encoder.decode(plain)

        content = plain[16:]
        xml_len = socket.ntohl(struct.unpack("I", content[:4])[0])
        xml_content = content[4: 4 + xml_len]
        from_corp = content[4 + xml_len:].decode("utf-8")
        if from_corp != self.corp_id:
            raise WeComCryptoError("corp id not match")
        return xml_content.decode("utf-8")

    def encrypt(self, reply_xml: str, nonce: str, timestamp: str) -> str:
        rand = _gen_random_str(16).encode("utf-8")
        xml_bytes = reply_xml.encode("utf-8")
        msg_len = struct.pack("I", socket.htonl(len(xml_bytes)))
        corp = self.corp_id.encode("utf-8")
        plain = PKCS7Encoder.encode(rand + msg_len + xml_bytes + corp)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        encrypted = base64.b64encode(cipher.encrypt(plain)).decode("utf-8")
        signature = _sha1(self.token, timestamp, nonce, encrypted)
        return (
            "<xml>"
            f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce>"
            "</xml>"
        )


def parse_xml_text(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    data = {}
    for child in root:
        data[child.tag] = child.text
    return data


def build_text_reply_xml(to_user: str, from_user: str, content: str, create_time: str) -> str:
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{create_time}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )

