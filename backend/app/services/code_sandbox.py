"""代码题沙箱判卷（设计文档 §9 后置）。

轻量沙箱：临时目录隔离 + 进程超时 + 输出大小限制。
支持语言：
- python：后端虚拟环境 Python（立即可用）
- c：检测 gcc，有则编译执行，无则返回 unavailable

安全说明：Windows 无原生容器，本沙箱做进程级隔离（超时/输出限制/临时目录），
适用于学习场景（用户自己的代码）。公网部署前需替换为 Docker/容器方案。
"""
import logging
import os
import subprocess
import tempfile
import uuid

logger = logging.getLogger("ailearn.code_sandbox")

EXEC_TIMEOUT_SEC = 5
MAX_OUTPUT_BYTES = 64 * 1024  # 64KB
MAX_CODE_BYTES = 16 * 1024  # 16KB

# 后端虚拟环境 Python（用于执行 Python 代码题）
_VENV_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".venv", "Scripts", "python.exe",
)

# 检测 gcc
_GCC = None
for _candidate in ("gcc", r"C:\MinGW\bin\gcc.exe", r"C:\msys64\mingw64\bin\gcc.exe"):
    try:
        r = subprocess.run([_candidate, "--version"], capture_output=True, timeout=3)
        if r.returncode == 0:
            _GCC = _candidate
            break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        continue


def available_languages() -> list[str]:
    langs = ["python"]
    if _GCC:
        langs.append("c")
    return langs


def _run_subprocess(cmd: list[str], stdin: str, cwd: str, timeout: int) -> dict:
    """执行子进程，返回 stdout/stderr/returncode/timed_out。"""
    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return {
            "stdout": proc.stdout[:MAX_OUTPUT_BYTES],
            "stderr": proc.stderr[:MAX_OUTPUT_BYTES],
            "returncode": proc.returncode,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "执行超时", "returncode": -1, "timed_out": True}
    except Exception as e:
        return {"stdout": "", "stderr": f"执行异常: {e}", "returncode": -1, "timed_out": False}


def run_python(code: str, stdin: str = "", timeout: int = EXEC_TIMEOUT_SEC) -> dict:
    """执行 Python 代码，返回执行结果。"""
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return {"stdout": "", "stderr": "代码过长", "returncode": -1, "timed_out": False}
    with tempfile.TemporaryDirectory(prefix="ailearn_py_") as tmpdir:
        code_path = os.path.join(tmpdir, "main.py")
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)
        return _run_subprocess([_VENV_PY, code_path], stdin, tmpdir, timeout)


def run_c(code: str, stdin: str = "", timeout: int = EXEC_TIMEOUT_SEC) -> dict:
    """编译并执行 C 代码。gcc 不可用时返回 unavailable。"""
    if not _GCC:
        return {"stdout": "", "stderr": "C 编译器(gcc)不可用", "returncode": -1, "timed_out": False, "unavailable": True}
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return {"stdout": "", "stderr": "代码过长", "returncode": -1, "timed_out": False}
    with tempfile.TemporaryDirectory(prefix="ailearn_c_") as tmpdir:
        src_path = os.path.join(tmpdir, "main.c")
        exe_path = os.path.join(tmpdir, "main.exe")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(code)
        # 编译
        compile_r = _run_subprocess([_GCC, src_path, "-o", exe_path, "-std=c11", "-Wall"], "", tmpdir, timeout)
        if compile_r["returncode"] != 0:
            return {"stdout": "", "stderr": f"编译错误:\n{compile_r['stderr']}", "returncode": -1, "timed_out": False}
        # 执行
        return _run_subprocess([exe_path], stdin, tmpdir, timeout)


def grade_code(payload: dict, user_code: str) -> dict:
    """代码题判卷：按测试用例执行，返回得分和反馈。

    payload 需包含 test_cases: [{"input": "...", "expected": "..."}]
    可选 language 字段（默认 python）。
    返回 {"score": 0-100, "feedback": "...", "passed": N, "total": N}
    """
    test_cases = payload.get("test_cases") or []
    if not test_cases:
        return {"score": None, "feedback": "题目无测试用例，回退 AI 评分", "passed": 0, "total": 0, "fallback": True}

    language = (payload.get("language") or "python").lower()
    runner = {"python": run_python, "c": run_c}.get(language)
    if runner is None:
        return {"score": None, "feedback": f"不支持的语言: {language}", "passed": 0, "total": len(test_cases), "fallback": True}

    passed = 0
    details = []
    for i, tc in enumerate(test_cases):
        stdin = str(tc.get("input", ""))
        expected = str(tc.get("expected", "")).strip()
        result = runner(user_code, stdin)
        if result.get("unavailable"):
            return {"score": None, "feedback": result["stderr"], "passed": 0, "total": len(test_cases), "fallback": True}
        actual = result["stdout"].strip()
        if result["timed_out"]:
            details.append(f"用例{i+1}: 超时")
        elif result["returncode"] != 0:
            details.append(f"用例{i+1}: 运行错误 ({result['stderr'][:80]})")
        elif actual == expected:
            passed += 1
            details.append(f"用例{i+1}: 通过")
        else:
            details.append(f"用例{i+1}: 错误 (期望: {expected[:40]} | 实际: {actual[:40]})")

    total = len(test_cases)
    score = int(passed / total * 100) if total > 0 else 0
    feedback = f"通过 {passed}/{total} 个测试用例\n" + "\n".join(details)
    return {"score": score, "feedback": feedback, "passed": passed, "total": total, "fallback": False}
