import asyncio
import json
import datetime
import logging
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

# Define the agent's JID and password from environment variables
PORTFOLIO_ANALYSIS_AGENT_JID = os.getenv("PORTFOLIO_ANALYSIS_AGENT_JID")
PORTFOLIO_ANALYSIS_AGENT_PASSWORD = os.getenv("PORTFOLIO_ANALYSIS_AGENT_PASSWORD")

# Define the PortfolioAnalysisAgent class
class PortfolioAnalysisAgent(Agent):
    def __init__(self, jid, password, auto_register=True):
        super().__init__(jid, password)
        # For future real API integration, if needed
        self._custom_auto_register = auto_register

    def _init_client(self):
        return XMPPClient(
            self.jid,
            self.password,
            verify_security=False,
            auto_register=self._custom_auto_register  # use this
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
                    portfolio_items = data["parameters"].get("portfolio")
                    task_id = data["task_id"]
                    parent = data["parent_task"]
                    reply_to = data["reply_to"]

                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "analyze_portfolio":
                        total_value = 0.0
                        detailed_holdings = []

                        simulated_prices = {
                            "GOOG": 175.00,
                            "MSFT": 420.00,
                            "AAPL": 190.00
                        }

                        for item in portfolio_items:
                            symbol = item.get("symbol")
                            shares = item.get("shares")
                            if symbol and shares is not None:
                                price = simulated_prices.get(symbol, 0.0)
                                value = price * shares
                                total_value += value
                                detailed_holdings.append({
                                    "symbol": symbol,
                                    "shares": shares,
                                    "current_price": price,
                                    "value": value
                                })
                            else:
                                status = "failure"
                                error_info = {
                                    "code": "INVALID_PORTFOLIO_ITEM",
                                    "message": f"Invalid item: {item}"
                                }
                                break

                        if status == "success":
                            result_data = {
                                "portfolio_summary": {
                                    "total_value": round(total_value, 2),
                                    "num_holdings": len(portfolio_items)
                                },
                                "holdings_details": detailed_holdings
                            }
                            logging.info(f"[PortfolioAnalysisAgent] Analysis complete. Total value: {total_value}")

                    else:
                        status = "failure"
                        error_info = {
                            "code": "UNEXPECTED_INTENT",
                            "message": f"Unexpected intent: {intent}"
                        }
                        logging.warning(f"[PortfolioAnalysisAgent] Unexpected intent received: {intent}")

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
                        logging.info(f"[PortfolioAnalysisAgent] Successfully processed request {task_id} for intent '{intent}'")
                    else:
                        reply_mcp["error"] = error_info
                        logging.error(f"[PortfolioAnalysisAgent] Error processing request {task_id} for intent '{intent}': {error_info}")

                    reply = Message(to=reply_to)
                    reply.set_metadata("performative", "inform" if status == "success" else "failure")
                    reply.set_metadata("ontology", "finance-task")
                    reply.body = json.dumps(reply_mcp)

                    await self.send(reply)
                    logging.info(f"[PortfolioAnalysisAgent] Response sent to {reply_to} (Status: {status})")

                except json.JSONDecodeError:
                    logging.error(f"[PortfolioAnalysisAgent] Malformed JSON from {msg.sender}: {msg.body}")
                except Exception as e:
                    logging.error(f"[PortfolioAnalysisAgent] Exception in behaviour: {str(e)}")

    async def setup(self):
        print(f"[PortfolioAnalysisAgent] Agent {self.jid} started.")
        self.presence.set_available()
        logging.info(f"[PortfolioAnalysisAgent] Presence set to available.")

        # Optional: Register service with DF
        register_service(
            "finance-data-provider",
            "analyze_portfolio",
            str(self.jid),
            {
                "description": "Agent for analyzing financial portfolios"
            }
        )
        logging.info(f"[PortfolioAnalysisAgent] Service registered.")

        # Bind template to filter incoming messages
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
