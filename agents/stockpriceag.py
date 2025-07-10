import json
import datetime
import httpx
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from df_registry import register_service
from dotenv import load_dotenv
from spade.xmpp_client import XMPPClient
import os
import logging
import asyncio
load_dotenv()

# Ensure the logs directory exists
os.makedirs("logs", exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="logs/stockpriceagent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
STOCK_PRICE_WORKER_JID = os.getenv("STOCK_PRICE_WORKER_JID")
STOCK_PRICE_WORKER_PASSWORD = os.getenv("STOCK_PRICE_WORKER_PASSWORD")

class StockPriceAgent(Agent):
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
    
    
    class HandleStockPriceRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    print(f"[StockPriceAgent] Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    symbol = data["parameters"].get("symbol")
                    task_id = data["task_id"]
                    parent = data["parent_task"]
                    reply_to = data["reply_to"]
                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "get_stock_price":
                        print(f"[StockPriceAgent] Fetching stock price for {symbol}...")
                        try:
                            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
                            async with httpx.AsyncClient() as client:
                                response = await client.get(url, timeout=10)
                                response.raise_for_status()
                                api_data = response.json()

                            if "Global Quote" in api_data and api_data["Global Quote"]:
                                price = api_data["Global Quote"].get("05. price")
                                if price:
                                    result_data = {
                                        "symbol": symbol,
                                        "price": float(price)
                                    }
                                    print(f"[StockPriceAgent] Price for {symbol}: {price}")
                                else:
                                    status = "failure"
                                    error_info = {"code": "API_DATA_ERROR", "message": f"No price found for {symbol}"}
                            else:
                                status = "failure"
                                error_info = {"code": "INVALID_RESPONSE", "message": "Unexpected API structure"}

                        except Exception as e:
                            status = "failure"
                            error_info = {"code": "EXCEPTION", "message": str(e)}

                    else:
                        status = "failure"
                        error_info = {"code": "INVALID_INTENT", "message": f"Unexpected intent: {intent}"}

                    reply_payload = {
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
                        reply_payload["result"] = result_data
                        logging.info(f"[StockPriceAgent] Successfully processed task {task_id} for intent '{intent}'")
                    else:
                        reply_payload["error"] = error_info
                        logging.error(f"[StockPriceAgent] Error processing task {task_id} for intent '{intent}': {error_info}")

                    reply = Message(to=reply_to)
                    reply.set_metadata("performative", "inform" if status == "success" else "failure")
                    reply.set_metadata("ontology", "finance-task")
                    reply.body = json.dumps(reply_payload)
                    await self.send(reply)

                except Exception as e:
                    print(f"[StockPriceAgent] Internal Error: {e}")

    async def setup(self):
        print(f"[StockPriceAgent] Agent {str(self.jid)} starting...")
        logging.info(f"[StockPriceAgent] Agent {str(self.jid)} starting...")
        self.presence.set_available()

        # Register service to DF_REGISTRY
        register_service("finance-data-provider", "get_stock_price", str(self.jid), {
            "description": "Provides real-time stock prices via Alpha Vantage"
        })

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleStockPriceRequest(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = StockPriceAgent(STOCK_PRICE_WORKER_JID, STOCK_PRICE_WORKER_PASSWORD)
        await agent.start(auto_register=True)
        print("[StockPriceAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("[StockPriceAgent] Stopping agent...")
            await agent.stop()
            print("[StockPriceAgent] Agent shutdown complete.")

    asyncio.run(run_agent())