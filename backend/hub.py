# -*- coding: utf-8 -*-
"""事件总线：训练线程 -> event loop -> WebSocket 订阅者。

附带历史事件缓存，因此客户端晚于训练启动才连上 WebSocket 也不会丢数据，
刷新页面后重新订阅同一实验即可完整回放。
"""
import asyncio


class Hub:
    def __init__(self):
        self._states: dict[str, dict] = {}

    def create(self, exp_id: str):
        self._states[exp_id] = {"events": [], "subs": set(), "done": False}

    def get(self, exp_id: str):
        return self._states.get(exp_id)

    def publish(self, exp_id: str, event: dict):
        state = self._states.get(exp_id)
        if state is None:
            return
        state["events"].append(event)
        for queue in list(state["subs"]):
            queue.put_nowait(event)
        if event.get("type") in ("done", "error"):
            state["done"] = True

    def publish_from_thread(self, loop: asyncio.AbstractEventLoop,
                            exp_id: str, event: dict):
        loop.call_soon_threadsafe(self.publish, exp_id, event)

    def subscribe(self, exp_id: str):
        state = self._states.get(exp_id)
        if state is None:
            state = {"events": [], "subs": set(), "done": False}
            self._states[exp_id] = state
        queue: asyncio.Queue = asyncio.Queue()
        state["subs"].add(queue)
        return queue, list(state["events"])

    def unsubscribe(self, exp_id: str, queue: asyncio.Queue):
        state = self._states.get(exp_id)
        if state:
            state["subs"].discard(queue)

    def is_done(self, exp_id: str) -> bool:
        state = self._states.get(exp_id)
        return bool(state and state["done"])
