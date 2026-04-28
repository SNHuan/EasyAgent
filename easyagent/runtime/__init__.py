"""Multi-agent runtime: agents + bus + pluggable scheduling.

    from easyagent.runtime import ShuffledRuntime, DeliverToRecipients, StopWhenIdle

    runtime = ShuffledRuntime(
        agents={"alice": alice, "bob": bob},
        step_policy=DeliverToRecipients(),
        stop_policy=StopWhenIdle(grace_steps=1),
    )
    result = await runtime.run([MessageEvent(...)])

For finer control, use ``TickBasedRuntime`` directly with an explicit
``schedule_policy``:

    from easyagent.runtime import TickBasedRuntime, Shuffled

    runtime = TickBasedRuntime(
        agents={"alice": alice, "bob": bob},
        step_policy=DeliverToRecipients(),
        stop_policy=StopWhenIdle(),
        schedule_policy=Shuffled(),
    )
"""

from easyagent.runtime.base import (
    BaseRuntime,
    ParallelRuntime,
    RuntimeResult,
    SequentialRuntime,
    ShuffledRuntime,
    TickBasedRuntime,
)
from easyagent.runtime.policies import (
    AnyOf,
    DeliverToRecipients,
    Delivery,
    Parallel,
    Sequential,
    Shuffled,
    SchedulePolicy,
    StopAfterEvents,
    StopAfterTicks,
    StopWhenIdle,
    StopWhenMessageMatches,
    StopPolicy,
    StepPolicy,
    TickDriven,
)
from easyagent.runtime.state import RuntimeState

__all__ = [
    "BaseRuntime",
    "TickBasedRuntime",
    "RuntimeResult",
    "RuntimeState",
    # Implementations (presets that pre-fill schedule_policy)
    "ParallelRuntime",
    "SequentialRuntime",
    "ShuffledRuntime",
    # Policy protocols
    "StepPolicy",
    "StopPolicy",
    "SchedulePolicy",
    "Delivery",
    # Step policies
    "DeliverToRecipients",
    "TickDriven",
    # Schedule policies
    "Parallel",
    "Sequential",
    "Shuffled",
    # Stop policies
    "AnyOf",
    "StopAfterEvents",
    "StopAfterTicks",
    "StopWhenIdle",
    "StopWhenMessageMatches",
]
