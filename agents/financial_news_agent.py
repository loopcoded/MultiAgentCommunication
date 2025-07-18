import json
import os
import httpx
import logging
import asyncio
from datetime import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from dotenv import load_dotenv
from df_registry import register_service
from spade.xmpp_client import XMPPClient
from utils.metrics import track_metrics
# Load environment variables
load_dotenv()

# Logging setup
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("financial_news_agent")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.FileHandler("logs/financial_news_agent.log", mode='a')
    formatter = logging.Formatter('%(asctime)s || %(levelname)s || %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Suppress verbose SPADE logs
logging.getLogger("spade.Agent").setLevel(logging.WARNING)

# Agent credentials from env
FINANCIAL_NEWS_AGENT_JID = os.getenv("FINANCIAL_NEWS_AGENT_JID")
FINANCIAL_NEWS_AGENT_PASSWORD = os.getenv("FINANCIAL_NEWS_AGENT_PASSWORD")
NEWS_API_KEY = os.getenv("NEWS_API_KEY") 


class FinancialNewsAgent(Agent):
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

    class HandleFinancialNewsRequest(CyclicBehaviour):
        @track_metrics  # Decorator to track metrics
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    logger.info(f"Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    params = data.get("parameters", {})
                    query = params.get("query") or params.get("company") or "finance"
                    limit = int(params.get("limit", 3))

                    task_id = data.get("task_id")
                    parent = data.get("parent_task")
                    reply_to = data.get("reply_to")

                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "get_financial_news":
                        logger.info(f"Fetching news for '{query}' (limit: {limit})")
                        url = "https://newsapi.org/v2/everything"
                        payload = {
                            "q": query,
                            "language": "en",
                            "pageSize": limit,
                            "sortBy": "publishedAt",
                            "apiKey": NEWS_API_KEY
                        }

                        try:
                            async with httpx.AsyncClient() as client:
                                response = await client.get(url, params=payload, timeout=10)
                                response.raise_for_status()
                                api_data = response.json()

                            if api_data.get("status") == "ok" and api_data.get("articles"):
                                articles = [
                                    {
                                        "title": a.get("title"),
                                        "source": a.get("source", {}).get("name"),
                                        "date": a.get("publishedAt"),
                                        "url": a.get("url")
                                    } for a in api_data["articles"]
                                ]
                                result_data = {"query": query, "articles": articles}
                                logger.info(f"Fetched {len(articles)} articles.")
                            else:
                                status = "failure"
                                error_info = {
                                    "code": "NEWS_API_NO_DATA",
                                    "message": f"No results for query: '{query}'"
                                }

                        except httpx.HTTPStatusError as e:
                            status = "failure"
                            error_info = {
                                "code": "HTTP_ERROR",
                                "message": f"HTTP {e.response.status_code}: {e.response.text}"
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
                                "code": "UNEXPECTED_ERROR",
                                "message": str(e)
                            }

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
                    logger.info(f"Sent response to {reply_to} with status: {status}")

                except json.JSONDecodeError:
                    logger.error(f"Malformed JSON from {msg.sender}: {msg.body}")
                except Exception as e:
                    logger.exception(f"Exception occurred: {str(e)}")

    async def setup(self):
        print(f"[FinancialNewsAgent] Agent {self.jid} started.")
        logger.info(f"Agent {self.jid} initialized.")
        self.presence.set_available()
        logger.info(f"Presence set to available.")

        register_service(
            "finance-data-provider",
            "get_financial_news",
            str(self.jid),
            {"description": "Agent for fetching real-time financial news using NewsAPI"}
        )
        logger.info("Service registered in DF.")

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
