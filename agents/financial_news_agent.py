import json
import os
import logging
from datetime import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from dotenv import load_dotenv
from df_registry import register_service
from spade.xmpp_client import XMPPClient
import asyncio
# Load environment variables
load_dotenv()

# Logging setup
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/financialnewsagent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)
# Define the agent's JID and password from environment variables
FINANCIAL_NEWS_AGENT_JID = os.getenv("FINANCIAL_NEWS_AGENT_JID")
FINANCIAL_NEWS_AGENT_PASSWORD = os.getenv("FINANCIAL_NEWS_AGENT_PASSWORD")

# Define the FinancialNewsAgent class
class FinancialNewsAgent(Agent):
    def __init__(self, jid, password, auto_register=True):
        super().__init__(jid, password)
        self._custom_auto_register = auto_register

    def _init_client(self):
        return XMPPClient(
            self.jid,
            self.password,
            verify_security=False,
            auto_register=self._custom_auto_register  # use this
        )
    
    
    class HandleFinancialNewsRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    logging.info(f"[FinancialNewsAgent] Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    query = data["parameters"].get("query")
                    limit = data["parameters"].get("limit", 1)
                    task_id = data["task_id"]
                    parent = data["parent_task"]
                    reply_to = data["reply_to"]

                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "get_financial_news":
                        logging.info(f"[FinancialNewsAgent] Simulating news fetch for '{query}' (limit: {limit})")

                        if query == "ERROR_NEWS":
                            status = "failure"
                            error_info = {
                                "code": "NEWS_API_ERROR",
                                "message": f"Simulated error fetching news for '{query}'"
                            }
                            logging.warning(f"[FinancialNewsAgent] Simulated error for query: {query}")
                        else:
                            articles = [
                                {
                                    "title": f"Google reports strong Q1 earnings, shares up {i + 1}%",
                                    "source": "Financial Times",
                                    "date": "2025-07-06",
                                    "url": "https://example.com/news1"
                                } for i in range(limit)
                            ]
                            result_data = {
                                "query": query,
                                "articles": articles
                            }
                            logging.info(f"[FinancialNewsAgent] Simulated financial news for '{query}'")

                    else:
                        status = "failure"
                        error_info = {
                            "code": "UNEXPECTED_INTENT",
                            "message": f"Unexpected intent: {intent}"
                        }
                        logging.error(f"[FinancialNewsAgent] Unexpected intent: {intent}")

                    reply_mcp = {
                        "protocol": "finance_mcp",
                        "version": "1.0",
                        "type": "response",
                        "task_id": task_id,
                        "parent_task": parent,
                        "intent": intent,
                        "status": status,
                        "timestamp": datetime.utcnow().isoformat()
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
                    logging.info(f"[FinancialNewsAgent] Sent response to {reply_to} with status: {status}")

                except json.JSONDecodeError:
                    logging.error(f"[FinancialNewsAgent] Malformed JSON from {msg.sender}: {msg.body}")
                except Exception as e:
                    logging.exception(f"[FinancialNewsAgent] Exception: {str(e)}")

    async def setup(self):
        print(f"[FinancialNewsAgent] Agent {self.jid} started.")
        logging.info(f"[FinancialNewsAgent] Agent {self.jid} initialized.")
        self.presence.set_available()
        logging.info(f"[FinancialNewsAgent] Presence set to available.")
        register_service(
            "finance-data-provider",
            "get_financial_news",
            str(self.jid),
            {
                "description": "Agent for fetching financial news articles"
            }
        )
        logging.info(f"[FinancialNewsAgent] Service registered.")

        # Template for this specific intent
        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleFinancialNewsRequest(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = FinancialNewsAgent(FINANCIAL_NEWS_AGENT_JID, FINANCIAL_NEWS_AGENT_PASSWORD)
        await agent.start(auto_register=True)
        print("[FinancialNewsAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("[FinancialNewsAgent] Stopping agent...")
            await agent.stop()
            print("[FinancialNewsAgent] Agent shutdown complete.")

    asyncio.run(run_agent())