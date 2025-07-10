import os
import asyncio
import logging
from dotenv import load_dotenv

from agents.manager import ManagerAgent
from agents.stockpriceag import StockPriceAgent
from agents.newsag import NewsSentimentAgent
from agents.portfolio_analysis_agent import PortfolioAnalysisAgent
from agents.financial_news_agent import FinancialNewsAgent
from agents.historical_data_agent import HistoricalDataAgent

# Load environment variables
load_dotenv()

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/manager.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)

async def main():
    print(" [Main] Starting all agents...")

    # Initialize agents
    stock_worker_agent = StockPriceAgent(
        os.getenv("STOCK_PRICE_WORKER_JID"),
        os.getenv("STOCK_PRICE_WORKER_PASSWORD")
    )
    sentiment_worker_agent = NewsSentimentAgent(
        os.getenv("NEWS_SENTIMENT_WORKER_JID"),
        os.getenv("NEWS_SENTIMENT_WORKER_PASSWORD")
    )
    portfolio_analysis_agent = PortfolioAnalysisAgent(
        os.getenv("PORTFOLIO_ANALYSIS_AGENT_JID"),
        os.getenv("PORTFOLIO_ANALYSIS_AGENT_PASSWORD")
    )
    financial_news_agent = FinancialNewsAgent(
        os.getenv("FINANCIAL_NEWS_AGENT_JID"),
        os.getenv("FINANCIAL_NEWS_AGENT_PASSWORD")
    )
    historical_data_agent = HistoricalDataAgent(
        os.getenv("HISTORICAL_DATA_WORKER_JID"),
        os.getenv("HISTORICAL_DATA_WORKER_PASSWORD")
    )
    manager = ManagerAgent(
        os.getenv("MANAGER_JID"),
        os.getenv("MANAGER_PASSWORD")
    )

    # Start agents with auto_register=True
    await asyncio.gather(
        stock_worker_agent.start(auto_register=True),
        sentiment_worker_agent.start(auto_register=True),
        portfolio_analysis_agent.start(auto_register=True),
        financial_news_agent.start(auto_register=True),
        historical_data_agent.start(auto_register=True),
    )

    print("[Main] Waiting 3s for agents to register with DF...")
    await asyncio.sleep(3)

    await manager.start(auto_register=True)

    print("[Main] All agents launched. Running... (Ctrl+C to stop)")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("[Main] Stopping agents...")
        await asyncio.gather(
            manager.stop(),
            stock_worker_agent.stop(),
            sentiment_worker_agent.stop(),
            portfolio_analysis_agent.stop(),
            financial_news_agent.stop(),
            historical_data_agent.stop()
        )
        print("[Main] Shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())
