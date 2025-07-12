import json
import os
import logging
import httpx
from datetime import datetime,timedelta
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from dotenv import load_dotenv
import asyncio
from dateutil.relativedelta import relativedelta 
from df_registry import register_service
from spade.xmpp_client import XMPPClient

load_dotenv()

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/historicaldataagent.log",
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s"
)
logging.getLogger("spade.Agent").setLevel(logging.WARNING)

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
                    task_id = data.get("task_id")
                    parent_task = data.get("parent_task")
                    reply_to = data.get("reply_to")
                    symbol = params.get("symbol")
                    period = params.get("period", "1 month")
                    print(f"[HistoricalDataAgent] Fetching historical data for: {symbol}, Period: {period}")

                    result_data = None
                    status = "success"
                    error_info = None

                    try:
                        url = f"https://www.alphavantage.co/query"
                        query_params = {
                            "function": "TIME_SERIES_DAILY",
                            "symbol": symbol,
                            "outputsize": "compact",  # last 100 data points
                            "apikey": ALPHA_VANTAGE_API_KEY
                        }

                        async with httpx.AsyncClient() as client:
                            response = await client.get(url, params=query_params, timeout=10)
                            response.raise_for_status()
                            api_data = response.json()
                    
                        # Inside the handler:
                        if "Time Series (Daily)" in api_data:
                            today = datetime.utcnow().date()
                        
                            # Parse period string
                            delta_days = 30  # Default
                            if "month" in period:
                                try:
                                    count = int(period.split()[0])
                                    delta_days = 30 * count
                                except:
                                    pass
                            elif "year" in period:
                                try:
                                    count = int(period.split()[0])
                                    delta_days = 365 * count
                                except:
                                    pass
                        
                            threshold_date = today - timedelta(days=delta_days)                        
                            historical = []
                            for date_str, values in api_data["Time Series (Daily)"].items():
                                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                                if date_obj >= threshold_date:
                                    historical.append({
                                        "date": date_str,
                                        "close_price": float(values["4. close"])
                                    })
                        
                            result_data = {
                                "symbol": symbol,
                                "period": period,
                                "data_points": historical[:30]  # Limit for performance, tune as needed
                            }
                        
                        
                    except httpx.RequestError as e:
                        status = "failure"
                        error_info = {
                            "code": "HTTP_REQUEST_ERROR",
                            "message": str(e)
                        }
                    except Exception as e:
                        status = "failure"
                        error_info = {
                            "code": "UNEXPECTED_ERROR",
                            "message": str(e)
                        }

                    # Prepare reply MCP message
                    reply_mcp = {
                        "protocol": "finance_mcp",
                        "version": "1.0",
                        "type": "subtask_response",
                        "task_id": task_id,
                        "parent_task": parent_task,
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
                    print(f"[HistoricalDataAgent] Responded to {reply_to} with {status}")

                except Exception as e:
                    logging.exception(f"[HistoricalDataAgent] Unexpected error: {e}")
    
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
                "description": "Fetches historical stock data using Alpha Vantage"
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
