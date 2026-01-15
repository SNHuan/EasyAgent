"""Test script for saving agent conversation logs to file.

Usage:
    python -m test.test_log_save
"""

import asyncio
from datetime import datetime
from pathlib import Path

from easyagent.agent.react_agent import ReactAgent
from easyagent.config.base import ModelConfig
from easyagent.debug.log import LogCollector, LogRecord
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.tool import register_tool


@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "Get the weather for a city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"The weather in {city} is sunny, 25°C."


def format_log_record(record: LogRecord) -> str:
    """Format a log record for file output."""
    ts = record.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{record.name}]" if record.name else ""
    return f"{ts} {record.level.value:5} {prefix} {record.message}"


def save_logs_to_file(
    records: list[LogRecord],
    task_id: str,
    log_dir: str | Path = "./workspace/logs",
) -> Path:
    """Save log records to file.
    
    Args:
        records: List of log records to save
        task_id: Task identifier
        log_dir: Directory to save logs (default: /workspace/logs)
    
    Returns:
        Path to the saved log file
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{timestamp}_{task_id}.log"
    
    content = "\n".join(format_log_record(r) for r in records)
    log_file.write_text(content, encoding="utf-8")
    
    return log_file


async def run_agent_with_logging(task_id: str, query: str) -> tuple[str, Path]:
    """Run agent and save all logs to file.
    
    Args:
        task_id: Task identifier for log filename
        query: User query to send to agent
    
    Returns:
        Tuple of (agent result, log file path)
    """
    config = ModelConfig.load()
    model = LiteLLMModel(**config.get_model("gemini-2.5-flash"))
    
    agent = ReactAgent(
        model=model,
        tools=["get_weather"],
        system_prompt="You are a helpful assistant.",
        max_iterations=5,
    )
    
    with LogCollector() as collector:
        result = await agent.run(query)
        log_file = save_logs_to_file(collector.records, task_id)
    
    return result, log_file


async def main():
    task_id = "weather_query_001"
    query = "What's the weather in Beijing and Shanghai?"
    
    print(f"Running agent with task_id: {task_id}")
    print(f"Query: {query}")
    print("-" * 50)
    
    result, log_file = await run_agent_with_logging(task_id, query)
    
    print("-" * 50)
    print(f"Result: {result}")
    print(f"Logs saved to: {log_file}")
    
    # Display saved log content
    print("\n=== Saved Log Content ===")
    print(log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())

