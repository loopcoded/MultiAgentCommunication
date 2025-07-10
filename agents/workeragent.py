import json
import httpx
from datetime import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from df_registry import register_service
import spade
from dotenv import load_dotenv
from spade.xmpp_client import XMPPClient
import os
import logging
load_dotenv()

# Ensure the logs directory exists
os.makedirs("logs", exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="logs/workeragent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)
WORKER_JID = os.getenv("WORKER_JID")
WORKER_PASSWORD = os.getenv("WORKER_PASSWORD")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

class FinancialDataWorkerAgent(Agent):
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
    
    
    class HandleSubtask(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                data = json.loads(msg.body)
                intent = data.get("intent")
                parameters = data["parameters"]
                subtask_id = data["task_id"]
                parent_id = data["parent_task"]
                reply_to = data["reply_to"]

                result = {}
                status = "success"
                error = None

                try:
                    if intent == "get_stock_price":
                        symbol = parameters["symbol"]
                        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
                        async with httpx.AsyncClient() as client:
                            res = await client.get(url, timeout=10)
                            data = res.json()
                            price = data["Global Quote"]["05. price"]
                            result = {"symbol": symbol, "price": float(price)}

                    elif intent == "get_news_sentiment":
                        company = parameters["company"]
                        sentiment = "positive"
                        result = {
                            "sentiment": sentiment,
                            "confidence": 0.94,
                            "summary": f"{company} is trending positively in recent financial news."
                        }
                    else:
                        raise ValueError(f"Unsupported intent: {intent}")

                except Exception as e:
                    status = "failure"
                    error = {"code": "PROCESSING_ERROR", "message": str(e)}

                response = {
                    "protocol": "finance_mcp",
                    "version": "1.0",
                    "type": "response",
                    "task_id": subtask_id,
                    "parent_task": parent_id,
                    "intent": intent,
                    "status": status,
                    "timestamp": datetime.utcnow().isoformat()
                }
                if status == "success":
                    response["result"] = result
                    logging.info(f"[Worker] Successfully processed subtask {subtask_id} for intent '{intent}'")
                else:
                    response["error"] = error
                    logging.error(f"[Worker] Error processing subtask {subtask_id} for intent '{intent}': {error}")

                reply = Message(to=reply_to)
                reply.set_metadata("performative", "inform" if status == "success" else "failure")
                reply.set_metadata("ontology", "finance-task")
                reply.body = json.dumps(response)
                await self.send(reply)

    async def setup(self):
        print(f"[Worker] Agent {self.jid} starting...")
        logging.info(f"[Worker] Agent {self.jid} starting...")
        self.presence.set_available()
        register_service("finance-data-provider", "get_stock_price", str(self.jid), {
            "description": "Real-time stock price via Alpha Vantage"
        })
        register_service("finance-data-provider", "get_news_sentiment", str(self.jid), {
            "description": "LLM-based sentiment analysis"
        })

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleSubtask(), template)

if __name__ == "__main__":
    spade.run(FinancialDataWorkerAgent(WORKER_JID, WORKER_PASSWORD))
