#!/usr/bin/env python3
"""reasonix-send-message CLI 入口。

从 Reasonix 权威数据源（~/.reasonix/config.toml 等）加载配置，
通过 sender 注册表遍历所有启用的平台并发送消息。

用法：
    python send.py "消息内容"
    python send.py --help
"""

import argparse
import sys

from send_message import SENDERS
from send_message.config import resolve_config, get_text_source, ConfigError


def _resolve_text(args: argparse.Namespace, cfg: dict) -> str:
    """确定消息文本。"""
    if args.text:
        return args.text

    src = get_text_source(cfg)
    if src["source"] == "file":
        path = src.get("path", "")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except (OSError, IOError) as e:
                print(f"❌ 读取文本文件失败: {e}", file=sys.stderr)
                sys.exit(1)

    print(
        "❌ 未指定消息文本。请通过命令行参数提供：python send.py \"消息内容\"",
        file=sys.stderr,
    )
    sys.exit(1)


def _print_report(results: list) -> None:
    """打印发送结果报告。"""
    all_ok = True
    for r in results:
        if r.get("ok"):
            print(f"✅ {r['channel']}: 发送成功")
        elif r.get("code") == "skipped":
            print(f"⏭️  {r['channel']}: 已跳过（配置中禁用）")
        else:
            all_ok = False
            print(f"❌ {r['channel']}: {r.get('msg', '失败')}")

    if not all_ok:
        sys.exit(1)


def _setup_encoding() -> None:
    """在 Windows 终端下确保 UTF-8 输出。"""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except AttributeError:
                pass


def main() -> None:
    _setup_encoding()
    parser = argparse.ArgumentParser(description="向飞书和微信发送文本消息")
    parser.add_argument("text", nargs="?", default="", help="消息文本内容")
    args = parser.parse_args()

    # 加载配置
    try:
        cfg = resolve_config()
    except ConfigError as e:
        print(f"❌ 配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    text = _resolve_text(args, cfg)

    # 通过注册表遍历所有 sender
    results = []
    for name, sender in SENDERS.items():
        platform_cfg = cfg.get(name, {})
        if not platform_cfg.get("enabled", False):
            continue

        # 校验必填字段
        missing = [k for k in sender.REQUIRED_KEYS if not platform_cfg.get(k)]
        if missing:
            results.append({
                "ok": False,
                "code": "missing",
                "msg": (
                    f"{sender.CHANNEL_NAME} 缺少必填配置: "
                    f"{', '.join(missing)}。"
                    f"请检查 ~/.reasonix/config.toml 对应字段。"
                ),
                "channel": sender.CHANNEL_NAME,
            })
            continue

        # 发送
        result = sender.send(text, cfg)
        result["channel"] = sender.CHANNEL_NAME
        results.append(result)

    if not results:
        print("⚠️  所有渠道均已禁用，无消息发送。")
        return

    _print_report(results)


if __name__ == "__main__":
    main()
