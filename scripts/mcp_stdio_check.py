"""以真实 MCP 客户端的方式拉起 stdio 服务，验证：
1. JSON-RPC 握手与 tools/list 正常；
2. stdout 是纯净的协议流（任何 print / banner 混入都会导致 JSON 解析失败）。

运行：uv run python scripts/mcp_stdio_check.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_python() -> str:
    """优先用项目虚拟环境的解释器。"""
    venv = ROOT / ".venv"
    for candidate in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    python = find_python()
    print(f"[check] interpreter: {python}")

    stderr_log = ROOT / "temp" / "mcp-stdio-check.err"
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    with open(stderr_log, "w", encoding="utf-8") as err_file:
        proc = subprocess.Popen(
            [python, str(ROOT / "mcp_server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err_file,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
        )
        return _drive(proc, stderr_log)


def _drive(proc: subprocess.Popen, stderr_log: Path) -> int:

    def request(method: str, params: dict | None = None, rid: int | None = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if rid is not None:
            message["id"] = rid
        if params is not None:
            message["params"] = params
        proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def read_response() -> dict:
        line = proc.stdout.readline()
        if not line:
            # 进程已退出，把服务端日志带出来便于定位
            detail = stderr_log.read_text(encoding="utf-8")[-2000:] if stderr_log.exists() else ""
            raise RuntimeError(f"服务关闭了 stdout，未收到响应。服务端输出：\n{detail}")
        return json.loads(line)  # stdout 一旦混入非协议输出，这里会直接报错

    try:
        request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-check", "version": "0.1.0"},
            },
            rid=1,
        )
        init = read_response()
        print("[check] serverInfo:", init["result"]["serverInfo"])

        request("notifications/initialized")

        request("tools/list", {}, rid=2)
        tools = read_response()["result"]["tools"]
        print("[check] tools:", [tool["name"] for tool in tools])

        request("tools/call", {"name": "bilibili_list_models", "arguments": {}}, rid=3)
        result = read_response()["result"]
        text = result["content"][0]["text"].replace("\n", " ")
        print(f"[check] call result: {text[:100]}...")

        print("[check] OK：stdio 协议流干净，工具可调用")
        return 0
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
