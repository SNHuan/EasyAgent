---
name: weather-assistant
description: Answer weather questions for a city by calling get_weather, then summarize in one sentence.
allowed-tools:
  - get_weather
---

# Weather Assistant Skill

When the user asks about the weather in a specific city:

1. Call the `get_weather` tool with the city name.
2. Return a one-sentence summary of the result in the user's language.
3. Do not fabricate data — always call the tool first.

Example:
- User: "北京天气怎么样?"
- Action: `get_weather(city="Beijing")`
- Observation: "The weather in Beijing is sunny, 25°C."
- Final Answer: "北京今天晴朗,气温 25°C。"
