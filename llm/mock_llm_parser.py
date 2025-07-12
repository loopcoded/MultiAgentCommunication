import os
import json
import datetime
import requests
from dotenv import load_dotenv

load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL = "gemini-1.5-flash"  # Use flash for free tier
GEN_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GOOGLE_API_KEY}"

async def gemini_llm_call(user_query: str, task_id: str) -> dict:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    system_prompt = f"""
You are a financial natural language parser.

Given a user query, generate a JSON object in this format:

{{
  "protocol": "finance_mcp",
  "version": "1.0",
  "type": "composite_request",
  "task_id": "{task_id}",
  "client_id": "user_console",
  "intents": [
    {{
      "intent": "<one of: get_stock_price, get_news_sentiment, get_financial_news, analyze_portfolio, get_historical_data>",
      "parameters": {{
        // Intent-specific parameters
      }}
    }}
  ],
  "timestamp": "{timestamp}"
}}

Define `parameters` per intent as follows:

1. get_stock_price:
{{
  "symbol": "<stock ticker symbol>"
}}

2. get_news_sentiment:
{{
  "company": "<company name or stock symbol>"
}}

3. get_financial_news:
{{
  "company": "<company name or stock symbol>"
}}

4. analyze_portfolio:
{{
  "holdings": [
    {{"symbol": "TSLA", "allocation": "40%"}},
    {{"symbol": "AAPL", "allocation": "30%"}}
  ]
}}

5. get_historical_data:
{{
  "symbol": "<ticker>"
}}

✔ Convert company names to official stock ticker symbols where possible.
✔ If query includes multiple tasks (e.g., “Get AAPL price and news”), return each in the `intents` array.
✔ Respond with only valid JSON — no markdown, no comments, no extra text.

User Query: {user_query}
"""

    payload = {
        "contents": [
            {"parts": [{"text": system_prompt}]}
        ]
    }

    try:
        response = requests.post(GEN_URL, json=payload)
        response.raise_for_status()

        model_text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        if model_text.startswith("```"):
            model_text = model_text.strip("`").split("\n", 1)[-1]

        return json.loads(model_text)

    except Exception as e:
        print(f"[LLM Parser] Error: {e}")
        return None