"""未部署草稿：每次仅一个自然段，默认只校验；不导入现有批量脚本。"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

URL = "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"
MAX_CHARACTERS = 800
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text_file", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--speaker", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--style-file", type=Path)
    args = parser.parse_args()
    raw = args.text_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("稿件摘要不符")
    text = raw.decode("utf-8").strip()
    if not text or len(text) > MAX_CHARACTERS or "\n" in text or "\r" in text:
        raise ValueError("仅允许一个自然段，最多800字符")
    if not args.speaker.startswith("zh_") or len(args.speaker) > 100:
        raise ValueError("声线参数不合法")
    if not args.execute:
        print(f"仅校验通过：{len(text)}字符，0次生成请求")
        return
    key = os.environ.get("ARK_API_KEY", "").strip()
    if not key:
        raise ValueError("套餐凭据未配置")
    output = Path("tts-single-output")
    if output.exists():
        raise ValueError("输出目录已存在，停止以免重复生成")
    # 无自动重试、无按量端点、无图片/视频/云盘请求；密钥仅内存及请求头。
    payload = {"user": {"uid": "yiwenbu"}, "req_params": {
        "text": text, "speaker": args.speaker,
        "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": 0}}}
    if args.style_file:
        style = args.style_file.read_text(encoding="utf-8").strip()
        if not style or len(style) > 1000:
            raise ValueError("风格上下文异常")
        payload["req_params"]["additions"] = json.dumps({"context_texts": [style]}, ensure_ascii=False)
    request = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "X-Api-Key": key,
        "Authorization": f"Bearer {key}", "X-Api-Resource-Id": "seed-tts-2.0"})
    # 不接受重定向，防止凭据随请求转发到其他端点。
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=120) as response:
            blob = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        print(f"套餐HTTP状态：{exc.code}；停止，不重试", file=sys.stderr)
        return 1
    except Exception as exc:
        # 不打印异常消息、响应体或请求头；超时同样不自动重试。
        print("请求失败；未重试。异常类型：" + type(exc).__name__, file=sys.stderr)
        return 1
    if len(blob) > MAX_RESPONSE_BYTES:
        raise ValueError("响应体超过上限，停止")
    audio = bytearray()
    for line in blob.splitlines():
        if not line.strip():
            continue
        part = json.loads(line)
        if part.get("code", 0) not in (0, 20000000):
            raise ValueError("服务返回失败，停止，不打印响应内容")
        if part.get("data"):
            audio.extend(base64.b64decode(part["data"], validate=True))
    if not audio:
        raise ValueError("服务未返回音频")
    output.mkdir()
    (output / "paragraph.mp3").write_bytes(audio)
    (output / "receipt.json").write_text(json.dumps({
        "input_sha256": args.sha256, "characters": len(text), "request_count": 1,
        "audio_sha256": hashlib.sha256(audio).hexdigest(), "audio_bytes": len(audio)}, indent=2))
    print("已取得一个自然段音频；听感未验收")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("停止。异常类型：" + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
