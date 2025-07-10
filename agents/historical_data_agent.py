import json
import os
import logging
from datetime import datetime
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from dotenv import load_dotenv
import asyncio
from df_registry import register_service
from spade.xmpp_client import XMPPClient
# Load environment variables
load_dotenv()

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/historicaldataagent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)
# Define the agent's JID and password from environment variables
HISTORICAL_DATA_WORKER_JID = os.getenv("HISTORICAL_DATA_WORKER_JID")
HISTORICAL_DATA_WORKER_PASSWORD = os.getenv("HISTORICAL_DATA_WORKER_PASSWORD")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

# Define the HistoricalDataAgent class
class HistoricalDataAgent(Agent):
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
    

    class HandleHistoricalDataRequest(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                try:
                    data = json.loads(msg.body) 
                    intent = data.get("intent", "")
                    params = data.get("parameters", {})
    
                    symbol = params.get("symbol")
                    period = params.get("period")
                    data_points = params.get("data_points")
    
                    print(f"[HistoricalDataAgent] Fetching historical data for {symbol}, period={period}, points={data_points}")
    
                    # Simulate data or call real API
                    historical_data = [
                        {"date": "2024-07-01", "price": 290.0},
                        {"date": "2024-07-02", "price": 293.0},
                        # ...simulate up to 100 points
                    ]
    
                    reply = Message(to=data["reply_to"])
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("ontology", "finance-task")
                    reply.body = json.dumps({
                        "protocol": "finance_mcp",
                        "version": "1.0",
                        "type": "subtask_response",
                        "task_id": data["task_id"],
                        "parent_task": data["parent_task"],
                        "status": "success",
                        "result": historical_data,
                        "timestamp": datetime.utcnow().isoformat()
                    })
    
                    await self.send(reply)
                    print(f"[HistoricalDataAgent] Sent response for {symbol}")
    
                except Exception as e:
                    logging.error(f"[HistoricalDataAgent] Exception occurred: {e}")
    
    async def setup(self):
        print(f"[HistoricalDataAgent] Agent {self.jid} starting...")
        logging.info(f"[HistoricalDataAgent] Agent {self.jid} setup initiated.")
        self.presence.set_available()
        logging.info(f"[HistoricalDataAgent] Presence set to available.")

        # Register service
        register_service(
            "finance-data-provider",
            "get_historical_data",
            str(self.jid),
            {
                "description": "Agent for fetching historical financial data"
            }
        )
        logging.info(f"[HistoricalDataAgent] Service registered.")

        template = Template()
        template.set_metadata("performative", "request")
        template.set_metadata("ontology", "finance-task")
        self.add_behaviour(self.HandleHistoricalDataRequest(), template)

if __name__ == "__main__":
    async def run_agent():
        agent = HistoricalDataAgent(HISTORICAL_DATA_WORKER_JID, HISTORICAL_DATA_WORKER_PASSWORD)
        await agent.start(auto_register=True)
        print("[HistoricalDataAgent] Agent is running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("[HistoricalDataAgent] Stopping agent...")
            await agent.stop()
            print("[HistoricalDataAgent] Shutdown complete.")

    asyncio.run(run_agent())
