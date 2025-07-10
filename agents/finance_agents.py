import asyncio
import json
import spade
import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template
from spade.presence import PresenceManager
from df_registry import register_service, search_service
import httpx
import logging
import os
import logging
from dotenv import load_dotenv
import os

load_dotenv()

# Ensure the logs directory exists
os.makedirs("logs", exist_ok=True)

# Configure logging
logging.basicConfig(
    filename="logs/manager_agent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)
# --- Configuration (Keep these consistent with your Prosody setup) ---

MANAGER_JID = os.getenv("MANAGER_JID")
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD")
WORKER_JID = os.getenv("WORKER_JID")
WORKER_PASSWORD = os.getenv("WORKER_PASSWORD")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

# --- Manager Agent ---
class ManagerAgent(Agent):
    def __init__(self, jid, password):
        super().__init__(jid, password)
        self.active_tasks = {}

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
                    {"intent": "get_news_sentiment", "parameters": {"company": "Tesla"}}
                ],
                "timestamp": datetime.datetime.utcnow().isoformat()
            }

            task_id = mcp_request["task_id"]
            self.agent.active_tasks[task_id] = {
                "client_id": mcp_request["client_id"],
                "status": "pending",
                "subtasks": {}
            }

            for i, intent in enumerate(mcp_request["intents"]):
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
                    "timestamp": datetime.datetime.utcnow().isoformat()
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
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        overall_status = "success"
        for st_id, st in self.active_tasks[task_id]["subtasks"].items():
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


# --- Financial Data Worker Agent ---
class FinancialDataWorkerAgent(Agent):

    class HandleSubtask(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                data = json.loads(msg.body)
                intent = data["intent"]
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
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
                if status == "success":
                    response["result"] = result
                else:
                    response["error"] = error

                reply = Message(to=reply_to)
                reply.set_metadata("performative", "inform" if status == "success" else "failure")
                reply.set_metadata("ontology", "finance-task")
                reply.body = json.dumps(response)
                await self.send(reply)

    async def set_service(self, service_type, service_name, properties=None):
        if properties is None:
            properties = {}
    
        service = {
            "type": service_type,
            "name": service_name,
            "properties": properties
        }
    
        await self.register_service(service)
        print(f"[Worker] Registered service: {service_name} (type: {service_type})")
        
    async def setup(self):
        print(f"[Worker] Agent {self.jid} starting...")
        self.presence.set_available()

        register_service("finance-data-provider", "get_stock_price", str(self.jid), {
            "description": "Real-time stock price via Alpha Vantage"
        })

        register_service("finance-data-provider", "get_news_sentiment", str(self.jid), {
            "description": "LLM-based sentiment analysis"
        })
    
        behaviour = self.HandleSubtask()
        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(behaviour, template)


async def main():
    worker = FinancialDataWorkerAgent(WORKER_JID, WORKER_PASSWORD)
    await worker.start()
    await asyncio.sleep(2)

    manager = ManagerAgent(MANAGER_JID, MANAGER_PASSWORD)
    await manager.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await manager.stop()
        await worker.stop()

if __name__ == "__main__":
    spade.run(main())

