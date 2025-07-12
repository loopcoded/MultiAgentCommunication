import json
import os
import asyncio
import datetime
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from llm.mock_llm_parser import gemini_llm_call
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
    format="%(asctime)s || %(levelname)s || %(message)s",
    force=True
)
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
            auto_register=self._custom_auto_register  # use this
        )
    
    class InteractiveInputBehaviour(CyclicBehaviour):
        async def run(self):
            user_query = input("\n[Client] Enter your financial query (e.g., 'What is TSLA stock price and news sentiment?'):\n> ")
            if not user_query.strip():
                print("[Client] No query entered. Waiting for next input...")
                await asyncio.sleep(1)
                return

            self.agent.task_counter += 1
            new_task_id = f"req_{self.agent.task_counter:03d}"
            print(f"[Manager] Received query: {user_query}" )

            mcp_request = await gemini_llm_call(user_query, new_task_id)
            if not mcp_request:
                print("[Manager] NLU failed to parse input.")
                return

            print("[Manager] Parsed MCP request:" )
            print(json.dumps(mcp_request, indent=2))

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

                print(f"[Manager] Searching DF for: {intent_data['intent']}" )
                matches = search_service("finance-data-provider", intent_data["intent"])

                if not matches:
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
                print(f"[Manager] Sending subtask {subtask_id} to {target_jid}" )
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
                        print(f"[Manager] Unknown task ID: {parent_task_id}")
                        return

                    task_ref = self.agent.active_tasks[parent_task_id]["subtasks"].get(subtask_id)
                    if not task_ref:
                        print(f"[Manager] Unknown subtask ID: {subtask_id}")
                        return

                    task_ref["status"] = status
                    task_ref["result"] = response.get("result") if status == "success" else None
                    task_ref["error"] = response.get("error") if status != "success" else None
                    print(f"[Manager] Subtask {subtask_id} -> {status}")
                    await self.agent.check_composite_task_completion(parent_task_id)
                except Exception as e:
                    print(f"[Manager] ERROR parsing worker response: {e}")

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

        print(f"\n[Client] Final response for {parent_task_id}:" )
        print(json.dumps(result_payload, indent=2) )
        print("\n--------------------------------------------------\n")
        await self.response_queue.put(True)

    async def setup(self):
        print(f"[Manager] Starting agent {self.jid}")
        self.presence.set_available()
        self.add_behaviour(self.InteractiveInputBehaviour())
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
