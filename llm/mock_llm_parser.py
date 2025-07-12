# llm/mock_llm_parser.py
import datetime

async def mock_nlu_llm_call(query: str, task_id: str) -> dict:
    current_time_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    query_lower = query.lower()
    intents = []

    if "stock price" in query_lower:
        symbol = "TSLA" if "tesla" in query_lower else "GOOG"
        intents.append({"intent": "get_stock_price", "parameters": {"symbol": symbol}})
    if "news sentiment" in query_lower:
        company = "Tesla" if "tesla" in query_lower else "Google"
        intents.append({"intent": "get_news_sentiment", "parameters": {"company": company}})
    if "historical data" in query_lower:
        symbol = "TSLA" if "tesla" in query_lower else "GOOG"
        intents.append({"intent": "get_historical_data", "parameters": {
            "symbol": symbol,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31"
        }})
    if "financial news" in query_lower:
        query_term = "Tesla updates"
        intents.append({"intent": "get_financial_news", "parameters": {"query": query_term, "limit": 3}})
    if "portfolio" in query_lower:
        intents.append({"intent": "analyze_portfolio", "parameters": {
            "portfolio": [{"symbol": "GOOG", "shares": 10}, {"symbol": "AAPL", "shares": 5}]
        }})

    if not intents:
        return None

    return {
        "protocol": "finance_mcp",
        "version": "1.0",
        "type": "composite_request",
        "task_id": task_id,
        "client_id": "user_console",
        "intents": intents,
        "timestamp": current_time_utc
    }
