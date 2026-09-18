import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silk_utils import encode_wav_to_silk


def _make_wav(rate: int = 24000, seconds: float = 0.1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def test_encode_wav_to_silk_returns_tencent_silk():
    silk = encode_wav_to_silk(_make_wav())
    assert silk.startswith(b"\x02#!SILK_V3")
    assert len(silk) > 0
