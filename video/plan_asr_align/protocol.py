"""Bounded SAUC v1 binary framing, independently implemented from official spec."""
import gzip
import io
import json
import struct

MAX_FRAME = 4 * 1024 * 1024


class ProtocolStop(Exception):
    pass


def encode(message_type, sequence, payload, final=False, serialization=0):
    if not 1 <= sequence <= 10000:
        raise ProtocolStop("Invalid outgoing sequence")
    compressed = gzip.compress(payload)
    if len(compressed) > MAX_FRAME:
        raise ProtocolStop("Outgoing frame exceeds limit")
    flags = 3 if final else 1
    header = bytes([0x11, message_type << 4 | flags, serialization << 4 | 1, 0])
    return header + struct.pack(">iI", -sequence if final else sequence, len(compressed)) + compressed


def full_request():
    # No reference text, hotword, correction, smoothing, or translation prompt.
    request = {"user": {"uid": "yiwenbu-r06-align"},
               "audio": {"format": "pcm", "codec": "raw", "rate": 16000,
                         "bits": 16, "channel": 1, "language": "zh-CN"},
               "request": {"model_name": "bigmodel", "show_utterances": True,
                           "result_type": "full", "enable_itn": False,
                           "enable_ddc": False, "enable_punc": True}}
    return encode(1, 1, json.dumps(request).encode(), serialization=1)


def decode(frame):
    if not isinstance(frame, bytes) or not 8 <= len(frame) <= MAX_FRAME:
        raise ProtocolStop("Invalid ASR frame size/type")
    version, header_size = frame[0] >> 4, (frame[0] & 15) * 4
    message_type, flags = frame[1] >> 4, frame[1] & 15
    serialization, compression = frame[2] >> 4, frame[2] & 15
    if version != 1 or header_size < 4 or header_size > 16 or len(frame) < header_size:
        raise ProtocolStop("Unsupported ASR header")
    if message_type not in (9, 15) or flags & ~7 or serialization != 1 or compression not in (0, 1):
        raise ProtocolStop("Unsupported ASR response encoding")
    offset, sequence, event = header_size, None, None
    def integer(signed=False):
        nonlocal offset
        if offset + 4 > len(frame):
            raise ProtocolStop("Truncated ASR frame")
        value = struct.unpack_from(">i" if signed else ">I", frame, offset)[0]
        offset += 4
        return value
    if flags & 1:
        sequence = integer(True)
    if flags & 4:
        event = integer(True)
    if message_type == 15:
        code = integer()
        raise ProtocolStop(f"ASR service error {code}; no retry")
    size = integer()
    if size > MAX_FRAME or offset + size != len(frame):
        raise ProtocolStop("ASR frame payload length mismatch")
    payload = frame[offset:]
    try:
        if compression == 1:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                payload = stream.read(MAX_FRAME + 1)
        if len(payload) > MAX_FRAME:
            raise ProtocolStop("ASR inflated payload exceeds limit")
        result = json.loads(payload)
    except (ValueError, OSError, EOFError):
        raise ProtocolStop("Malformed ASR JSON/compression") from None
    if not isinstance(result, dict) or result.get("code", 0) not in (0, 20000000):
        raise ProtocolStop("ASR returned failure; response text suppressed")
    return {"sequence": sequence, "event": event, "final": bool(flags & 2), "payload": result}
