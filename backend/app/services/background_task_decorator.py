"""@background_task 装饰器：零侵入将异步函数接入任务中心。

用法：
    @background_task(task_type="knowledge_refine", title="知识点细化")
    async def refine_node(node_id: int, force: bool = False):
        # 函数内可直接调用 task_center.update_progress(stage="...")
        # 会自动使用当前上下文的 task_id
        ...

    # 调用时立即返回 task_id，函数在后台执行
    task_id = refine_node(node_id=123)

    # 如果需要同步等待结果，传 _sync=True
    result = await refine_node(node_id=123, _sync=True)
"""
import asyncio
import functools
import inspect
import logging
from typing import Any, Callable, Coroutine

from . import task_center

logger = logging.getLogger("ailearn.background_task")


def background_task(
    task_type: str,
    title: str | Callable[..., str] = "",
    total_steps: int = 0,
):
    """装饰器：将异步函数包装为后台任务。

    Args:
        task_type: 任务类型标识
        title: 任务标题，字符串或函数（接收与被装饰函数相同的参数，返回标题）
        total_steps: 总步骤数
    """

    def decorator(func: Callable[..., Coroutine]) -> Callable[..., Any]:
        # 注册 runner 用于重试
        task_center.register_runner(task_type, func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 提取 _sync 参数（不传给原函数）
            sync = kwargs.pop("_sync", False)
            # 提取 user_key 参数（用于物理分库后任务归属，不传给原函数）
            task_user_key = kwargs.pop("user_key", None)

            # 计算标题
            if callable(title):
                try:
                    task_title = title(*args, **kwargs)
                except Exception:
                    task_title = func.__name__
            else:
                task_title = title or func.__name__

            # 构建 metadata（函数参数）
            metadata = _extract_metadata(func, args, kwargs)

            # 创建任务（带 user_key 归属）
            task_id = task_center.create_task(
                task_type=task_type,
                title=task_title,
                metadata=metadata,
                total_steps=total_steps,
                user_key=task_user_key,
            )

            if sync:
                # 同步执行：在当前协程中运行，等待完成
                return _run_sync(task_id, func, args, kwargs)

            # 异步执行：创建后台任务
            asyncio.create_task(_run_async(task_id, func, args, kwargs))
            return {"task_id": task_id, "status": "pending", "title": task_title}

        return wrapper

    return decorator


async def _run_async(task_id: str, func: Callable, args: tuple, kwargs: dict):
    """异步执行包装。"""
    token = task_center._current_task_id.set(task_id)
    try:
        task_center.mark_running(task_id)
        result = await func(*args, **kwargs)
        if task_center.is_cancelled(task_id):
            task_center.mark_cancelled(task_id)
        else:
            task_center.complete_task(task_id, _safe_result(result))
    except Exception as e:
        logger.exception("后台任务异常: id=%s func=%s", task_id, func.__name__)
        task_center.fail_task(task_id, str(e))
    finally:
        task_center._current_task_id.reset(token)


async def _run_sync(task_id: str, func: Callable, args: tuple, kwargs: dict):
    """同步执行包装（等待结果）。"""
    token = task_center._current_task_id.set(task_id)
    try:
        task_center.mark_running(task_id)
        result = await func(*args, **kwargs)
        if task_center.is_cancelled(task_id):
            task_center.mark_cancelled(task_id)
            return None
        task_center.complete_task(task_id, _safe_result(result))
        return result
    except Exception as e:
        logger.exception("后台任务异常(同步): id=%s func=%s", task_id, func.__name__)
        task_center.fail_task(task_id, str(e))
        raise
    finally:
        task_center._current_task_id.reset(token)


def _extract_metadata(func: Callable, args: tuple, kwargs: dict) -> dict:
    """从函数参数中提取可序列化的 metadata。"""
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        metadata = {}
        for key, value in bound.arguments.items():
            if key.startswith("_"):
                continue
            # 只保留可 JSON 序列化的简单类型
            if isinstance(value, (str, int, float, bool, type(None))):
                metadata[key] = value
            elif isinstance(value, (list, dict)):
                try:
                    import json
                    json.dumps(value, ensure_ascii=False)
                    metadata[key] = value
                except (TypeError, ValueError):
                    metadata[key] = str(value)[:200]
            else:
                metadata[key] = str(value)[:200]
        return metadata
    except Exception:
        return {}


def _safe_result(result: Any) -> dict | None:
    """将结果安全转为 dict（用于存储）。"""
    if result is None:
        return None
    if isinstance(result, dict):
        # 过滤不可序列化的值
        import json
        try:
            json.dumps(result, ensure_ascii=False, default=str)
            return result
        except (TypeError, ValueError):
            return {"summary": str(result)[:500]}
    return {"summary": str(result)[:500]}
