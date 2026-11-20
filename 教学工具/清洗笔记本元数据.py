"""剥除笔记本文件级元数据中的本机信息，供 git 提交时自动调用。

编辑器保存笔记本时会把当前内核名称写回 metadata，可能带上本机虚拟环境
目录名或解释器版本。本脚本只替换文件级 metadata，单元格与输出原样保留，
因此本地文件不受影响，进入仓库的版本保持中性。
"""

from __future__ import annotations

import json
import sys

# 与教学工具/检查笔记本.py 的 clean_metadata 保持一致。
GENERIC_METADATA = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        notebook = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # 不是合法笔记本时原样透传，交由 git 与编辑器暴露问题，不静默改坏文件。
        sys.stdout.buffer.write(raw)
        return 0
    notebook["metadata"] = GENERIC_METADATA
    text = json.dumps(notebook, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    # 直接写字节，避免 Windows 文本模式把换行改成 CRLF。
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
