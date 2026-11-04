import asyncio
import threading
from collections import defaultdict
from typing import Dict, Set, Tuple


class EventBus:
    """
    In-process pub/sub keyed by event_id.
    Subscribers are asyncio queues bound to the event loop they were created in.
    publish(event_id) may be called from any thread and delivers safely with
    loop.call_soon_threadsafe.
    Each subscriber queue has maxsize=100; when full, the oldest message is dropped.
    """

    def __init__(self, maxsize: int = 100) -> None:
        self.maxsize = maxsize
        self._lock = threading.Lock()
        # event_id -> set of (loop, queue)
        self._subscribers: Dict[int, Set[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(set)

    def subscribe(self, event_id: int) -> Tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        with self._lock:
            self._subscribers[event_id].add((loop, queue))
        return loop, queue

    def unsubscribe(self, event_id: int, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(event_id)
            if subs:
                subs.discard((loop, queue))
                if not subs:
                    del self._subscribers[event_id]

    def _deliver(self, queue: asyncio.Queue, event_id: int) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event_id)
        except asyncio.QueueFull:
            # If still full due to race, drop oldest again and put
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event_id)
            except asyncio.QueueFull:
                pass

    def publish(self, event_id: int) -> None:
        with self._lock:
            subs = list(self._subscribers.get(event_id, ()))

        for loop, queue in subs:
            if not loop.is_closed():
                loop.call_soon_threadsafe(self._deliver, queue, event_id)


bus = EventBus()
