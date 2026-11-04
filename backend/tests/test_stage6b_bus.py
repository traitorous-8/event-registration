import asyncio
import threading
import pytest
from backend.app.events_bus import EventBus


@pytest.mark.asyncio
async def test_bus_subscribe_publish_from_thread():
    bus = EventBus()
    loop, queue = bus.subscribe(1)

    def background_publisher():
        bus.publish(1)

    thread = threading.Thread(target=background_publisher)
    thread.start()
    thread.join()

    # Receive with timeout
    event_id = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event_id == 1

    bus.unsubscribe(1, loop, queue)
    assert 1 not in bus._subscribers


@pytest.mark.asyncio
async def test_bus_bounded_queue_drops_oldest():
    bus = EventBus(maxsize=3)
    loop, queue = bus.subscribe(42)

    # Put 3 messages
    bus.publish(42)
    bus.publish(42)
    bus.publish(42)

    # Let event loop process call_soon_threadsafe calls
    await asyncio.sleep(0.05)
    assert queue.qsize() == 3

    # Bus delivery dropped oldest if overflowing
    bus._deliver(queue, 999)
    assert queue.qsize() == 3

    # The items should be delivered with the oldest dropped
    item1 = queue.get_nowait()
    item2 = queue.get_nowait()
    item3 = queue.get_nowait()
    assert item3 == 999

    bus.unsubscribe(42, loop, queue)


@pytest.mark.asyncio
async def test_bus_unsubscribe_cleans_up():
    bus = EventBus()
    loop, queue = bus.subscribe(10)
    assert 10 in bus._subscribers
    assert len(bus._subscribers[10]) == 1

    bus.unsubscribe(10, loop, queue)
    assert 10 not in bus._subscribers

    # Unsubscribing non-existent is a safe no-op
    bus.unsubscribe(10, loop, queue)


@pytest.mark.asyncio
async def test_bus_publish_no_subscribers_noop():
    bus = EventBus()
    # Publishing to nonexistent event ID should not raise
    bus.publish(999)
