import json
import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from df_registry import register_service
import spade
from dotenv import load_dotenv
import os
from spade.xmpp_client import XMPPClient
import asyncio
import logging
load_dotenv()

# Ensure the logs directory exists
os.makedirs("logs", exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="logs/newsagent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)
NEWS_SENTIMENT_WORKER_JID = os.getenv('NEWS_SENTIMENT_WORKER_JID')
NEWS_SENTIMENT_WORKER_PASSWORD = os.getenv('NEWS_SENTIMENT_WORKER_PASSWORD')

class NewsSentimentAgent(Agent):
    def __init__(self, jid, password,auto_register=True):
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
    
    class HandleSentimentRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body)
                    print(f"[NewsSentimentAgent] Received task from {msg.sender}: {data}")

                    intent = data.get("intent")
                    company = data.get("parameters", {}).get("company")
                    task_id = data.get("task_id")
                    parent = data.get("parent_task")
                    reply_to = data.get("reply_to")

                    result_data = None
                    status = "success"
                    error_info = None

                    if intent == "get_news_sentiment":
                        print(f"[NewsSentimentAgent] Simulating LLM call for news sentiment of {company}...")

                        if company == "ERROR_COMPANY":
                            status = "failure"
                            error_info = {
                                "code": "LLM_API_ERROR",
                                "message": f"Simulated LLM error for {company}"
                            }
                        else:
                            simulated_llm_response_text = "Tesla's stock surges after strong Q2 delivery report. The overall sentiment is positive."
                            sentiment = "positive" if "positive" in simulated_llm_response_text.lower() else \
                                        "negative" if "negative" in simulated_llm_response_text.lower() else "neutral"
                            summary = simulated_llm_response_text.split(". The overall sentiment is")[0] + "."
                            confidence = 0.95

                            result_data = {
                                "sentiment": sentiment,
                                "confidence": confidence,
                                "summary": summary
                            }

                    else:
                        status = "failure"
                        error_info = {
                            "code": "UNEXPECTED_INTENT",
                            "message": f"NewsSentimentAgent received unexpected intent: {intent}"
                        }

                    reply_mcp = {
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
                        reply_mcp["result"] = result_data
                    else:
                        reply_mcp["error"] = error_info

                    reply = Message(to=reply_to)
                    reply.set_metadata("performative", "inform" if status == "success" else "failure")
                    reply.set_metadata("ontology", "finance-task")
                    reply.body = json.dumps(reply_mcp)

                    print(f"[NewsSentimentAgent] Sending response back to {reply_to} (Status: {status})...")
                    await self.send(reply)

                except json.JSONDecodeError:
                    print(f"[NewsSentimentAgent] ERROR: Received malformed JSON from {msg.sender}: {msg.body}")
                except Exception as e:
                    print(f"[NewsSentimentAgent] Unexpected error: {e}")

    async def setup(self):
        print(f"[NewsSentimentAgent] Agent {str(self.jid)} ready.")
        self.presence.set_available()

        register_service(
            "finance-data-provider",
            "get_news_sentiment",
            str(self.jid),
            {"description": "Provides news sentiment analysis using LLM"}
        )
        print(f"[NewsSentimentAgent] Service registered in DF.")

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleSentimentRequest(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = NewsSentimentAgent(NEWS_SENTIMENT_WORKER_JID, NEWS_SENTIMENT_WORKER_PASSWORD)
        await agent.start(auto_register=True)
        print("[NewsSentimentAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("[NewsSentimentAgent] Stopping agent...")
            await agent.stop()
            print("[NewsSentimentAgent] Shutdown complete.")

    asyncio.run(run_agent())
