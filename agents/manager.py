import json
import os
import asyncio
import datetime
import logging
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from llm.mock_llm_parser import gemini_llm_call
from df_registry import search_service
from dotenv import load_dotenv
from spade.xmpp_client import XMPPClient

load_dotenv()

# Configure custom logging
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("manager_agent")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.FileHandler("logs/manager_agent.log", mode='a')
    formatter = logging.Formatter('%(asctime)s || %(levelname)s || %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logging.getLogger("spade.Agent").setLevel(logging.WARNING)

MANAGER_JID = os.getenv("MANAGER_JID")
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD")

class ManagerAgent(Agent):
    def __init__(self, jid, password, auto_register=False):
        super().__init__(jid, password)
        self.task_counter = 0
        self.active_tasks = {}
        self.response_queue = asyncio.Queue()
        self._custom_auto_register = auto_register

    def _init_client(self):
        return XMPPClient(
            self.jid,
            self.password,
            verify_security=False,
            auto_register=self._custom_auto_register
        )

    class InteractiveInputBehaviour(CyclicBehaviour):
        async def run(self):
            user_query = input("\n[Client] Enter your financial query (e.g., 'What is TSLA stock price and news sentiment?'):\n> ")
            if not user_query.strip():
                logger.warning("[Client] No query entered. Waiting for next input...")
                await asyncio.sleep(1)
                return

            self.agent.task_counter += 1
            new_task_id = f"req_{self.agent.task_counter:03d}"
            logger.info(f"[Manager] Received query: {user_query}")

            mcp_request = await gemini_llm_call(user_query, new_task_id)
            if not mcp_request:
                logger.error("[Manager] NLU failed to parse input.")
                return

            logger.info("[Manager] Parsed MCP request:")
            logger.info(json.dumps(mcp_request, indent=2))

            parent_task_id = mcp_request["task_id"]
            self.agent.active_tasks[parent_task_id] = {
                "client_id": mcp_request["client_id"],
                "status": "pending",
                "subtasks": {},
                "final_response": {}
            }

            for intent_data in mcp_request["intents"]:
                subtask_id = f"{parent_task_id}_{intent_data['intent'].replace('get_', '').replace('analyze_', '')}"
                self.agent.active_tasks[parent_task_id]["subtasks"][subtask_id] = {
                    "intent": intent_data["intent"],
                    "status": "pending",
                    "result": None,
                    "error": None
                }

                logger.info(f"[Manager] Searching DF for: {intent_data['intent']}")
                matches = search_service("finance-data-provider", intent_data["intent"])

                if not matches:
                    logger.warning(f"[Manager] No agent found for intent: {intent_data['intent']}")
                    self.agent.active_tasks[parent_task_id]["subtasks"][subtask_id].update({
                        "status": "failure",
                        "error": {"code": "NO_WORKER_FOUND", "message": "No agent found"}
                    })
                    await self.agent.check_composite_task_completion(parent_task_id)
                    continue

                target_jid = matches[0]["jid"]
                subtask = {
                    "protocol": "finance_mcp",
                    "version": "1.0",
                    "type": "subtask_request",
                    "task_id": subtask_id,
                    "parent_task": parent_task_id,
                    "intent": intent_data["intent"],
                    "parameters": intent_data["parameters"],
                    "reply_to": str(self.agent.jid),
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }

                msg = Message(to=target_jid)
                msg.set_metadata("performative", "request")
                msg.set_metadata("ontology", "finance-task")
                msg.body = json.dumps(subtask)
                logger.info(f"[Manager] Sending subtask {subtask_id} to {target_jid}")
                await self.send(msg)

            await self.agent.response_queue.get()

    class ReceiveWorkerResponse(CyclicBehaviour):
        async def run(self):
            template = Template()
            template.set_metadata("ontology", "finance-task")
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    response = json.loads(msg.body)
                    parent_task_id = response.get("parent_task")
                    subtask_id = response.get("task_id")
                    status = response.get("status")

                    if parent_task_id not in self.agent.active_tasks:
                        logger.warning(f"[Manager] Unknown task ID: {parent_task_id}")
                        return

                    task_ref = self.agent.active_tasks[parent_task_id]["subtasks"].get(subtask_id)
                    if not task_ref:
                        logger.warning(f"[Manager] Unknown subtask ID: {subtask_id}")
                        return

                    task_ref["status"] = status
                    task_ref["result"] = response.get("result") if status == "success" else None
                    task_ref["error"] = response.get("error") if status != "success" else None
                    logger.info(f"[Manager] Subtask {subtask_id} -> {status}")
                    await self.agent.check_composite_task_completion(parent_task_id)
                except Exception as e:
                    logger.exception(f"[Manager] ERROR parsing worker response: {e}")

    def format_response(result_payload):
        lines = ["\n[Client] 🧾 Human-Readable Summary:"]
        for r in result_payload["results"]:
            intent = r["intent"]
            status = r["status"]
            if status != "success":
                lines.append(f"❌ {intent.replace('_', ' ').title()}: Failed - {r.get('error', {}).get('message', 'Unknown error')}")
                continue

            data = r.get("data", {})
            if intent == "get_stock_price":
                lines.append(f"📈 Stock Price of {data['symbol']}: ${data['price']}")
            elif intent == "get_news_sentiment":
                lines.append(f"🧠 Sentiment: {data['sentiment'].capitalize()} (Confidence: {data.get('confidence', '?')})")
                summary = data.get("summary", "")
                if summary:
                    lines.append(f"   Summary: {summary}")
            elif intent == "get_financial_news":
                lines.append(f"📰 Top News for {data['query']}:")
                for art in data.get("articles", [])[:2]:
                    lines.append(f"   - {art['title']} ({art['source']})")
            elif intent == "get_historical_data":
                lines.append(f"📊 Historical Data for {data['symbol']} ({data['period']}):")
                for pt in data.get("data_points", [])[:3]:
                    lines.append(f"   - {pt['date']}: ${pt['close_price']}")
            elif intent == "analyze_portfolio":
                lines.append("💼 Portfolio Breakdown:")
                for h in data["holdings_details"]:
                    lines.append(f"   - {h['symbol']}: {h['allocation_percent']}% → ${h['capital_allocated']} → Est. Shares: {h['estimated_shares']}")

        lines.append("\n[Client] ✅ Summary completed.\n--------------------------------------------------\n")
        return "\n".join(lines)

    async def check_composite_task_completion(self, parent_task_id):
        task_info = self.active_tasks.get(parent_task_id)
        if not task_info:
            return

        if any(st["status"] == "pending" for st in task_info["subtasks"].values()):
            return

        result_payload = {
            "protocol": "finance_mcp",
            "version": "1.0",
            "type": "composite_response",
            "task_id": parent_task_id,
            "client_id": task_info["client_id"],
            "results": [],
            "overall_status": "success",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        for st_id, sub in task_info["subtasks"].items():
            if sub["status"] == "success":
                result_payload["results"].append({"intent": sub["intent"], "status": "success", "data": sub["result"]})
            else:
                result_payload["results"].append({"intent": sub["intent"], "status": "failure", "error": sub["error"]})
                result_payload["overall_status"] = "partial_success"

        task_info["status"] = result_payload["overall_status"]
        task_info["final_response"] = result_payload

        logger.info(f"[Manager] Final response for {parent_task_id}: {json.dumps(result_payload, indent=2)}")
        print(ManagerAgent.format_response(result_payload))
        await self.response_queue.put(True)

    async def setup(self):
        logger.info(f"[Manager] Starting agent {self.jid}")
        self.presence.set_available()
        self.add_behaviour(self.InteractiveInputBehaviour())
        template = Template()
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.ReceiveWorkerResponse(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = ManagerAgent(MANAGER_JID, MANAGER_PASSWORD)
        await agent.start(auto_register=True)
        logger.info("[Manager] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("[Manager] Stopping agent...")
            await agent.stop()
            logger.info("[Manager] Agent shutdown complete.")

    asyncio.run(run_agent())
