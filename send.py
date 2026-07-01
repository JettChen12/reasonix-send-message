#!/usr/bin/env python3
"""reasonix-send-message CLI 入口。

从 Reasonix 权威数据源（~/.reasonix/config.toml 等）加载配置，
通过 sender 注册表遍历所有启用的平台并发送消息。

用法：
    python send.py "消息内容"
    python send.py --help
"""

import argparse
import logging
import sys

from send_message import SENDERS
from send_message.config import resolve_config, get_text_source, ConfigError
from send_message.setup import ensure_bot_config

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    """配置日志输出。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


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
    parser = argparse.ArgumentParser(description="向飞书、微信、QQ 等 Bot 发送文本消息")
    parser.add_argument("text", nargs="?", default="", help="消息文本内容")
    parser.add_argument(
        "-c", "--channel",
        action="append",
        dest="channels",
        choices=["feishu", "weixin", "qq"],
        help="指定发送渠道（可重复使用），不指定则发送所有已启用渠道。"
        " 例如：-c weixin  或  -c weixin -c feishu",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="输出调试信息（包括配置详情、API 请求日志等）",
    )
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)
    logger.info("reasonix-send-message 启动")

    # 确保有配置 — 没有就引导用户扫码/手动输入
    if not ensure_bot_config():
        print("⚠️  未配置 Bot，退出。")
        sys.exit(1)

    # 加载配置
    try:
        cfg = resolve_config()
    except ConfigError as e:
        print(f"❌ 配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    text = _resolve_text(args, cfg)
    logger.debug("消息文本（前 50 字符）: %s", text[:50])

    # 通过注册表遍历所有 sender，按 --channel 过滤
    results = []
    selected = args.channels  # None 表示全部
    for name, sender in SENDERS.items():
        if selected and name not in selected:
            logger.debug("%s: 未在 --channel 指定，跳过", name)
            continue
        platform_cfg = cfg.get(name, {})
        if not platform_cfg.get("enabled", False):
            logger.info("%s: 已禁用，跳过", getattr(sender, "CHANNEL_NAME", name))
            continue

        channel_name = getattr(sender, "CHANNEL_NAME", name)

        # 校验必填字段
        required = getattr(sender, "REQUIRED_KEYS", set())
        missing = [k for k in required if not platform_cfg.get(k)]
        if missing:
            results.append({
                "ok": False,
                "code": "missing",
                "msg": (
                    f"{channel_name} 缺少必填配置: "
                    f"{', '.join(missing)}。"
                    f"请检查 Reasonix 配置文件中对应字段。"
                ),
                "channel": channel_name,
            })
            logger.warning("%s: 缺少必填配置 %s", channel_name, missing)
            continue

        # 发送
        logger.info("%s: 发送中…", channel_name)
        result = sender.send(text, cfg)
        result["channel"] = channel_name
        results.append(result)

    if not results:
        print("⚠️  所有渠道均已禁用，无消息发送。")
        return

    _print_report(results)


if __name__ == "__main__":
    main()
