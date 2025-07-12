import os
import asyncio
import logging
import httpx
import json
import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from df_registry import register_service
from spade.xmpp_client import XMPPClient
from dotenv import load_dotenv

load_dotenv()

# Logging setup
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("news_sentiment_agent")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.FileHandler("logs/news_sentiment_agent.log", mode='a')
    formatter = logging.Formatter('%(asctime)s || %(levelname)s || %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logging.getLogger("spade.Agent").setLevel(logging.WARNING)

NEWS_SENTIMENT_WORKER_JID = os.getenv('NEWS_SENTIMENT_WORKER_JID')
NEWS_SENTIMENT_WORKER_PASSWORD = os.getenv('NEWS_SENTIMENT_WORKER_PASSWORD')
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class NewsSentimentAgent(Agent):
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

    class HandleSentimentRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    logger.info(f"[NewsSentimentAgent] Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    company = data.get("parameters", {}).get("company")
                    task_id = data.get("task_id")
                    parent = data.get("parent_task")
                    reply_to = data.get("reply_to")

                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "get_news_sentiment":
                        try:
                            logger.info(f"[NewsSentimentAgent] Querying Gemini API for company: {company}")
                            prompt = (
                                f"Summarize the most recent financial news about {company} "
                                "and determine the sentiment as 'positive', 'negative', or 'neutral'."
                            )
                            headers = {
                                "Content-Type": "application/json",
                                "X-goog-api-key": GEMINI_API_KEY
                            }
                            payload = {
                                "contents": [
                                    {
                                        "parts": [{"text": prompt}]
                                    }
                                ]
                            }
                            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

                            async with httpx.AsyncClient() as client:
                                response = await client.post(url, headers=headers, json=payload, timeout=20)
                                response.raise_for_status()
                                llm_response = response.json()

                            generated = llm_response["candidates"][0]["content"]["parts"][0]["text"]
                            sentiment = "positive" if "positive" in generated.lower() else \
                                        "negative" if "negative" in generated.lower() else "neutral"
                            summary = generated.split("The overall sentiment is")[0].strip().rstrip('.') + '.'
                            confidence = 0.90  # Placeholder

                            result_data = {
                                "sentiment": sentiment,
                                "confidence": confidence,
                                "summary": summary
                            }

                            logger.info(f"[NewsSentimentAgent] Sentiment: {sentiment} | Summary: {summary}")

                        except httpx.HTTPStatusError as e:
                            status = "failure"
                            error_info = {
                                "code": "GEMINI_HTTP_ERROR",
                                "message": f"Gemini HTTP Error: {e.response.status_code} - {e.response.text}"
                            }
                            logger.error(f"[NewsSentimentAgent] HTTP error: {e}")
                        except Exception as e:
                            status = "failure"
                            error_info = {
                                "code": "GEMINI_EXCEPTION",
                                "message": str(e)
                            }
                            logger.exception(f"[NewsSentimentAgent] Unexpected error during Gemini call.")
                    else:
                        status = "failure"
                        error_info = {
                            "code": "INVALID_INTENT",
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
                    logger.info(f"[NewsSentimentAgent] Response sent to {reply_to} | Status: {status}")

                except json.JSONDecodeError:
                    logger.error(f"[NewsSentimentAgent] Malformed JSON received from {msg.sender}: {msg.body}")
                except Exception as e:
                    logger.exception(f"[NewsSentimentAgent] Fatal error in processing message.")

    async def setup(self):
        logger.info(f"[NewsSentimentAgent] Agent {str(self.jid)} initialized.")
        self.presence.set_available()

        register_service(
            "finance-data-provider",
            "get_news_sentiment",
            str(self.jid),
            {"description": "Provides news sentiment analysis using LLM"}
        )
        logger.info(f"[NewsSentimentAgent] Service registered in DF.")

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleSentimentRequest(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = NewsSentimentAgent(NEWS_SENTIMENT_WORKER_JID, NEWS_SENTIMENT_WORKER_PASSWORD)
        await agent.start(auto_register=True)
        logger.info("[NewsSentimentAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("[NewsSentimentAgent] Stopping agent...")
            await agent.stop()
            logger.info("[NewsSentimentAgent] Shutdown complete.")

    asyncio.run(run_agent())
