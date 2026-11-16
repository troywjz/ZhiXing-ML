"""在新内核中执行课程、检查参考解，并可写回整理后的教学输出。"""

from __future__ import annotations

import argparse
import ast
import copy
import re
import sys
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[1]


def check_privacy(nb: nbformat.NotebookNode) -> None:
    """检查正文、文本输出和元数据中的本机信息及常见密钥格式。"""
    text_parts = [str(dict(nb.metadata))]
    for cell in nb.cells:
        text_parts.extend([cell.source, str(dict(cell.metadata))])
        for output in cell.get("outputs", []):
            if output.output_type == "error":
                raise ValueError("发现报错输出，请修复后重新运行")
            text_parts.append(str(output.get("text", "")))
            for mime, value in output.get("data", {}).items():
                if mime.startswith("text/") or mime == "image/svg+xml":
                    text_parts.append(str(value))
    text = "\n".join(text_parts)
    patterns = {
        "绝对路径": r"(?<![A-Za-z])[A-Za-z]:[\\/]|/(?:Users|home)/",
        "邮箱": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        "常见密钥": r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|-----BEGIN .*PRIVATE KEY",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, text):
            raise ValueError(f"发现{name}，请在本地检查对应内容")


def reference_cells(nb: nbformat.NotebookNode) -> list[nbformat.NotebookNode]:
    """只提取折叠区域中带断言的 Python 参考代码。"""
    cells = []
    for cell in nb.cells:
        if cell.cell_type != "markdown":
            continue
        for details in re.findall(r"<details\b[^>]*>(.*?)</details>", cell.source, re.S):
            for code in re.findall(r"```python\s*\n(.*?)```", details, re.S):
                if not re.search(r"\bassert\b", code):
                    raise ValueError("参考解缺少结果断言")
                cells.append(nbformat.v4.new_code_cell(code.strip()))
    return cells


def exercise_check_cells(nb: nbformat.NotebookNode) -> list[nbformat.NotebookNode]:
    """参考答案填入后执行带标签的自检分支，保留源笔记本中的默认关闭状态。"""
    checks = []
    for cell in nb.cells:
        if cell.cell_type != "code" or "exercise-check" not in cell.metadata.get("tags", []):
            continue
        for statement in ast.parse(cell.source).body:
            if isinstance(statement, ast.If):
                checks.append(nbformat.v4.new_code_cell("\n".join(ast.unparse(node) for node in statement.body)))
    return checks


def clean_metadata(nb: nbformat.NotebookNode) -> None:
    nb.metadata = nbformat.from_dict({
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    })
    for cell in nb.cells:
        tags = [tag for tag in cell.metadata.get("tags", []) if tag == "exercise-check"]
        cell.metadata = {"tags": tags} if tags else {}
        if cell.cell_type == "code":
            cell.execution_count = None
            for output in cell.outputs:
                if "execution_count" in output:
                    output.execution_count = None
                if "metadata" in output:
                    output.metadata = {}


def check(path: Path, save: bool) -> tuple[int, int, int]:
    source = nbformat.read(path, as_version=4)
    nbformat.validate(source)
    check_privacy(source)
    original_count = len(source.cells)
    executed = copy.deepcopy(source)
    solutions = reference_cells(source)
    executed.cells.extend(solutions)
    checks = exercise_check_cells(source)
    executed.cells.extend(checks)

    # 明确使用启动此脚本的项目解释器，避免系统 python3 内核指向其他环境。
    km = KernelManager(kernel_name="python3")
    km.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    try:
        client = NotebookClient(
            executed,
            km=km,
            timeout=120,
            allow_errors=False,
            resources={"metadata": {"path": str(path.parent)}},
        )
        client.execute()
    finally:
        # 外部传入的内核由本脚本负责关闭。
        if km.has_kernel:
            km.shutdown_kernel(now=True)
        km.cleanup_resources()

    executed.cells = executed.cells[:original_count]
    clean_metadata(executed)
    nbformat.validate(executed)
    check_privacy(executed)
    if save:
        nbformat.write(executed, path)
    code_count = sum(c.cell_type == "code" for c in source.cells)
    return code_count, len(solutions), len(checks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--保存输出", action="store_true", help="将审查后的教学输出写回课程，清理执行计数和机器元数据")
    args = parser.parse_args()
    paths = sorted((ROOT / "课程").rglob("*.ipynb"))
    paths = [p for p in paths if ".ipynb_checkpoints" not in p.parts]
    if not paths:
        print("尚无课程笔记本可检查")
        return 1
    failures = 0
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        try:
            code_count, solution_count, check_count = check(path, args.保存输出)
            print(f"通过：{relative}（{code_count} 个代码单元，{solution_count} 个参考解，{check_count} 个练习自检）")
        except Exception as error:
            failures += 1
            # 错误正文可能含本机路径，在控制台只显示类别。
            print(f"失败：{relative}（{type(error).__name__}；请在编辑器中定位失败单元）")
    print(f"检查结束：{len(paths) - failures}/{len(paths)} 本通过")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
