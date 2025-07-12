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

# Logging setup
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("stock_price_agent")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.FileHandler("logs/stock_price_agent.log", mode='a')
    formatter = logging.Formatter('%(asctime)s || %(levelname)s || %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logging.getLogger("spade.Agent").setLevel(logging.WARNING)

ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
STOCK_PRICE_WORKER_JID = os.getenv("STOCK_PRICE_WORKER_JID")
STOCK_PRICE_WORKER_PASSWORD = os.getenv("STOCK_PRICE_WORKER_PASSWORD")


class StockPriceAgent(Agent):
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

    class HandleStockPriceRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    logger.info(f"[StockPriceAgent] Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    symbol = data["parameters"].get("symbol")
                    task_id = data.get("task_id")
                    parent = data.get("parent_task")
                    reply_to = data.get("reply_to")

                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "get_stock_price":
                        logger.info(f"[StockPriceAgent] Fetching real-time stock price for {symbol}...")
                        try:
                            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
                            async with httpx.AsyncClient() as client:
                                response = await client.get(url, timeout=10)
                                response.raise_for_status()
                                api_data = response.json()

                            if "Global Quote" in api_data:
                                quote = api_data["Global Quote"]
                                price = quote.get("05. price")
                                if price:
                                    result_data = {
                                        "symbol": symbol,
                                        "price": float(price)
                                    }
                                    logger.info(f"[StockPriceAgent] Fetched price for {symbol}: {price}")
                                else:
                                    status = "failure"
                                    error_info = {
                                        "code": "DATA_MISSING",
                                        "message": f"Price missing in API response for {symbol}"
                                    }
                            elif "Error Message" in api_data:
                                status = "failure"
                                error_info = {
                                    "code": "API_ERROR",
                                    "message": api_data["Error Message"]
                                }
                            else:
                                status = "failure"
                                error_info = {
                                    "code": "UNKNOWN_FORMAT",
                                    "message": "Unexpected response format from Alpha Vantage"
                                }

                        except httpx.RequestError as e:
                            status = "failure"
                            error_info = {
                                "code": "NETWORK_ERROR",
                                "message": str(e)
                            }
                        except Exception as e:
                            status = "failure"
                            error_info = {
                                "code": "EXCEPTION",
                                "message": str(e)
                            }

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
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }

                    if status == "success":
                        reply_payload["result"] = result_data
                        logger.info(f"[StockPriceAgent] Task {task_id} processed successfully.")
                    else:
                        reply_payload["error"] = error_info
                        logger.error(f"[StockPriceAgent] Task {task_id} failed: {error_info}")

                    reply = Message(to=reply_to)
                    reply.set_metadata("performative", "inform" if status == "success" else "failure")
                    reply.set_metadata("ontology", "finance-task")
                    reply.body = json.dumps(reply_payload)

                    await self.send(reply)
                    logger.info(f"[StockPriceAgent] Response sent to {reply_to} | Status: {status}")

                except Exception as e:
                    logger.exception(f"[StockPriceAgent] Unhandled exception occurred: {e}")

    async def setup(self):
        logger.info(f"[StockPriceAgent] Agent {self.jid} setup initiated.")
        self.presence.set_available()
        logger.info(f"[StockPriceAgent] Presence set to available.")

        register_service(
            "finance-data-provider",
            "get_stock_price",
            str(self.jid),
            {"description": "Provides real-time stock prices via Alpha Vantage"}
        )
        logger.info(f"[StockPriceAgent] Service registered in DF.")

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleStockPriceRequest(), template)


if __name__ == "__main__":
    async def run_agent():
        agent = StockPriceAgent(STOCK_PRICE_WORKER_JID, STOCK_PRICE_WORKER_PASSWORD)
        await agent.start(auto_register=True)
        logger.info("[StockPriceAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("[StockPriceAgent] Shutdown initiated.")
            await agent.stop()
            logger.info("[StockPriceAgent] Agent shutdown complete.")

    asyncio.run(run_agent())
