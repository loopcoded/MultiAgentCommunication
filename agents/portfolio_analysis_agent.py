import asyncio
import json
import datetime
import logging
import httpx
import os
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from df_registry import register_service
from dotenv import load_dotenv
from spade.xmpp_client import XMPPClient

# Load environment variables
load_dotenv()

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/portfolio_agent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)

PORTFOLIO_ANALYSIS_AGENT_JID = os.getenv("PORTFOLIO_ANALYSIS_AGENT_JID")
PORTFOLIO_ANALYSIS_AGENT_PASSWORD = os.getenv("PORTFOLIO_ANALYSIS_AGENT_PASSWORD")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

class PortfolioAnalysisAgent(Agent):
    def __init__(self, jid, password, auto_register=True):
        super().__init__(jid, password)
        self._custom_auto_register = auto_register

    def _init_client(self):
        return XMPPClient(
            self.jid,
            self.password,
            verify_security=False,
            auto_register=self._custom_auto_register
        )

    class HandlePortfolioAnalysisRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    logging.info(f"[PortfolioAnalysisAgent] Received request: {data}")
                    print(f"[PortfolioAnalysisAgent] Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    portfolio_items = data["parameters"].get("holdings")
                    task_id = data["task_id"]
                    parent = data["parent_task"]
                    reply_to = data["reply_to"]

                    result_data = None
                    status = "success"
                    error_info = None
                    total_value = 0.0
                    detailed_holdings = []

                    if intent == "analyze_portfolio":
                        total_capital = 100000.0  # Simulated base capital

                        for item in portfolio_items:
                            symbol = item.get("symbol")
                            allocation_str = item.get("allocation")

                            if not symbol or not allocation_str:
                                status = "failure"
                                error_info = {
                                    "code": "INVALID_PORTFOLIO_ITEM",
                                    "message": f"Invalid portfolio item: {item}"
                                }
                                break

                            try:
                                allocation_percent = float(allocation_str.strip('%'))
                                capital_allocated = (allocation_percent / 100.0) * total_capital

                                url = f"https://www.alphavantage.co/query"
                                params = {
                                    "function": "GLOBAL_QUOTE",
                                    "symbol": symbol,
                                    "apikey": ALPHA_VANTAGE_API_KEY
                                }

                                async with httpx.AsyncClient() as client:
                                    response = await client.get(url, params=params, timeout=5)
                                    response.raise_for_status()
                                    api_data = response.json()

                                price_str = api_data.get("Global Quote", {}).get("05. price")
                                current_price = float(price_str) if price_str else 0.0
                                shares_estimated = round(capital_allocated / current_price, 2)

                                detailed_holdings.append({
                                    "symbol": symbol,
                                    "allocation_percent": allocation_percent,
                                    "capital_allocated": round(capital_allocated, 2),
                                    "estimated_shares": shares_estimated,
                                    "current_price": current_price
                                })
                                total_value += capital_allocated

                                logging.info(f"[PortfolioAnalysisAgent] {symbol}: {allocation_percent}% = ₹{capital_allocated}")

                            except Exception as e:
                                logging.error(f"[PortfolioAnalysisAgent] Error fetching price for {symbol}: {str(e)}")
                                status = "failure"
                                error_info = {
                                    "code": "API_FETCH_ERROR",
                                    "message": f"Could not fetch data for symbol: {symbol}"
                                }
                                break

                        if status == "success":
                            result_data = {
                                "portfolio_summary": {
                                    "total_estimated_value": round(total_value, 2),
                                    "base_capital": total_capital,
                                    "num_holdings": len(detailed_holdings)
                                },
                                "holdings_details": detailed_holdings
                            }
                            logging.info(f"[PortfolioAnalysisAgent] Total estimated value: ₹{total_value}")

                    else:
                        status = "failure"
                        error_info = {
                            "code": "UNEXPECTED_INTENT",
                            "message": f"Unexpected intent: {intent}"
                        }

                    reply_mcp = {
                        "protocol": "finance_mcp",
                        "version": "1.0",
                        "type": "response",
                        "task_id": task_id,
                        "parent_task": parent,
                        "intent": intent,
                        "status": status,
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    }
                    if status == "success":
                        reply_mcp["result"] = result_data
                    else:
                        reply_mcp["error"] = error_info

                    reply = Message(to=reply_to)
                    reply.set_metadata("performative", "inform" if status == "success" else "failure")
                    reply.set_metadata("ontology", "finance-task")
                    reply.body = json.dumps(reply_mcp)

                    await self.send(reply)
                    logging.info(f"[PortfolioAnalysisAgent] Sent reply to {reply_to} (Status: {status})")

                except json.JSONDecodeError:
                    logging.error(f"[PortfolioAnalysisAgent] Invalid JSON from {msg.sender}: {msg.body}")
                except Exception as e:
                    logging.error(f"[PortfolioAnalysisAgent] Unexpected error: {str(e)}")

    async def setup(self):
        print(f"[PortfolioAnalysisAgent] Agent {self.jid} started.")
        self.presence.set_available()
        logging.info(f"[PortfolioAnalysisAgent] Presence set to available.")

        register_service(
            "finance-data-provider",
            "analyze_portfolio",
            str(self.jid),
            {
                "description": "Agent for analyzing financial portfolios"
            }
        )
        logging.info(f"[PortfolioAnalysisAgent] Service registered.")

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandlePortfolioAnalysisRequest(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = PortfolioAnalysisAgent(PORTFOLIO_ANALYSIS_AGENT_JID, PORTFOLIO_ANALYSIS_AGENT_PASSWORD)
        await agent.start(auto_register=True)
        print("[PortfolioAnalysisAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("[PortfolioAnalysisAgent] Stopping agent...")
            await agent.stop()
            print("[PortfolioAnalysisAgent] Agent shutdown complete.")

    asyncio.run(run_agent())
