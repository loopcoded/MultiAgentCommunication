import json
import os
import asyncio
from datetime import datetime
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
import spade
from df_registry import search_service
from dotenv import load_dotenv
from spade.xmpp_client import XMPPClient
import os
import logging
load_dotenv()

# Ensure the logs directory exists
os.makedirs("logs", exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="logs/manager.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)


MANAGER_JID = os.getenv("MANAGER_JID")
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD")

class ManagerAgent(Agent):
    def __init__(self, jid, password, auto_register=False):
        super().__init__(jid, password)
        self.active_tasks = {}
        self._custom_auto_register = auto_register

    def _init_client(self):
        return XMPPClient(
            self.jid,
            self.password,
            verify_security=False,
            auto_register=self._custom_auto_register  # use this
        )
    
    class SimulateClientRequest(OneShotBehaviour):
        async def run(self):
            print("[Manager] Simulating client request...")
            mcp_request = {
                "protocol": "finance_mcp",
                "version": "1.0",
                "type": "composite_request",
                "task_id": "req_001",
                "client_id": "user_xyz",
                "intents": [
                    {"intent": "get_stock_price", "parameters": {"symbol": "TSLA"}},
                    {"intent": "get_news_sentiment", "parameters": {"company": "Tesla"}},
                    {"intent": "analyze_portfolio", "parameters": {"portfolio": [{"symbol": "TSLA", "shares": 3}, {"symbol": "AAPL", "shares": 5}, {"symbol": "GOOGL", "shares": 2}]}},
                    {"intent": "get_financial_news", "parameters": {"company": "Tesla"}},
                    {"intent": "get_historical_data", "parameters": {"symbol": "TSLA", "period": "1y","data_points": 100}}
                ],
                "timestamp": datetime.utcnow().isoformat()
            }

            task_id = mcp_request["task_id"]
            self.agent.active_tasks[task_id] = {
                "client_id": mcp_request["client_id"],
                "status": "pending",
                "subtasks": {}
            }

            for intent in mcp_request["intents"]:
                subtask_id = f"{task_id}_{intent['intent'].replace('get_', '')}"
                self.agent.active_tasks[task_id]["subtasks"][subtask_id] = {
                    "intent": intent["intent"],
                    "status": "pending",
                    "result": None
                }

                print(f"[Manager] Searching DF for service '{intent['intent']}'")
                matches = search_service("finance-data-provider", intent["intent"])
                if not matches:
                    print(f"[Manager] No worker found for intent: {intent['intent']}")
                    self.agent.active_tasks[task_id]["subtasks"][subtask_id]["status"] = "failure"
                    self.agent.active_tasks[task_id]["subtasks"][subtask_id]["result"] = {
                        "error": "NO_WORKER_FOUND"
                    }
                    continue

                worker_jid = matches[0]["jid"]
                msg = Message(to=worker_jid)
                msg.set_metadata("performative", "request")
                msg.set_metadata("ontology", "finance-task")
                msg.body = json.dumps({
                    "protocol": "finance_mcp",
                    "version": "1.0",
                    "type": "subtask_request",
                    "task_id": subtask_id,
                    "parent_task": task_id,
                    "intent": intent["intent"],
                    "parameters": intent["parameters"],
                    "reply_to": str(self.agent.jid),
                    "timestamp": datetime.utcnow().isoformat()
                })

                print(f"[Manager] Dispatching {intent['intent']} to {worker_jid}")
                await self.send(msg)

    class ReceiveWorkerResponse(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                response = json.loads(msg.body)
                task_id = response["parent_task"]
                subtask_id = response["task_id"]

                if task_id in self.agent.active_tasks:
                    subtask = self.agent.active_tasks[task_id]["subtasks"][subtask_id]
                    subtask["status"] = response["status"]
                    subtask["result"] = response.get("result") or response.get("error")

                    print(f"[Manager] Subtask {subtask_id} -> {response['status']}")

                    all_done = all(st["status"] != "pending"
                                   for st in self.agent.active_tasks[task_id]["subtasks"].values())

                    if all_done:
                        await self.agent.aggregate_final_result(task_id)

    async def aggregate_final_result(self, task_id):
        final_result = {
            "protocol": "finance_mcp",
            "version": "1.0",
            "type": "composite_response",
            "task_id": task_id,
            "results": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        overall_status = "success"
        for st in self.active_tasks[task_id]["subtasks"].values():
            result_entry = {
                "intent": st["intent"],
                "status": st["status"]
            }
            if st["status"] == "success":
                result_entry["data"] = st["result"]
            else:
                result_entry["error"] = st["result"]
                overall_status = "partial_success"
            final_result["results"].append(result_entry)
        final_result["overall_status"] = overall_status
        print("[Manager] Composite task result:")
        print(json.dumps(final_result, indent=2))

    async def setup(self):
        print(f"[Manager] Starting agent {self.jid}")
        self.presence.set_available()
        self.add_behaviour(self.SimulateClientRequest())
        template = Template()
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.ReceiveWorkerResponse(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = ManagerAgent(MANAGER_JID, MANAGER_PASSWORD)
        await agent.start(auto_register=True)
        print("[Manager] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("[Manager] Stopping agent...")
            await agent.stop()
            print("[Manager] Agent shutdown complete.")

    asyncio.run(run_agent())
