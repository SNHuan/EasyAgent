"""Memory-related prompt templates"""

SUMMARY_FORMAT = """\
# Conversation Summary

## Task Context
{task_context}

## Key Decisions
{key_decisions}

## Actions Taken
{actions_taken}

## Current State
{current_state}

## Important Information
{important_info}
"""

SUMMARY_PROMPT = """\
You are a conversation summarizer. Summarize the following conversation history into a structured format.

Focus on:
1. Task Context - What is the user trying to accomplish?
2. Key Decisions - Important choices or decisions made during the conversation
3. Actions Taken - Tools called, operations performed, and their results
4. Current State - Where are we in the task? What's completed, what's pending?
5. Important Information - Critical data, configurations, or context that must be preserved

Conversation to summarize:
{conversation}

Output your summary in the following JSON format:
```json
{{
    "task_context": "Brief description of the overall task",
    "key_decisions": ["decision 1", "decision 2"],
    "actions_taken": ["action 1 with result", "action 2 with result"],
    "current_state": "Current progress and pending items",
    "important_info": ["critical info 1", "critical info 2"]
}}
```

Be concise but preserve all critical information needed to continue the task.
"""

COMPRESS_SUMMARY_PROMPT = """\
You are a summary compressor. The current summary is too long and needs to be compressed to fit within {target_tokens} tokens.

Current summary:
{summary}

Compress this summary while preserving the most critical information:
1. Keep the overall task context
2. Keep the most recent and important decisions
3. Merge or remove redundant action records, keep only key milestones
4. Keep the current state accurate
5. Keep only the most critical information

Output your compressed summary in the following JSON format:
```json
{{
    "task_context": "Brief description of the overall task",
    "key_decisions": ["most important decision 1", "most important decision 2"],
    "actions_taken": ["key milestone 1", "key milestone 2"],
    "current_state": "Current progress and pending items",
    "important_info": ["critical info 1", "critical info 2"]
}}
```

Be aggressive in compression but never lose information critical to continuing the task.
"""

