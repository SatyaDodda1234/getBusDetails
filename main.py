import requests
from flask import Flask, request, jsonify
import os
from datetime import datetime, timezone
app = Flask(__name__)
TFL_APP_ID = os.environ.get("TFL_APP_ID")
TFL_APP_KEY = os.environ.get("TFL_APP_KEY")
SEARCH_URL = "https://api.tfl.gov.uk/StopPoint/Search/{}"
ARRIVALS_URL = "https://api.tfl.gov.uk/StopPoint/{}/Arrivals"
def get_stop_point_id(stop_name: str) -> str | None:
   params = {"app_id": TFL_APP_ID, "app_key": TFL_APP_KEY}
   resp = requests.get(SEARCH_URL.format(stop_name), params=params, timeout=10)
   resp.raise_for_status()
   matches = resp.json().get("matches", [])
   return None if not matches else matches[0]["id"]
@app.route("/", methods=["POST"])
def webhook_handler():
   req = request.get_json()
   session_info = req.get("sessionInfo", {})
   parameters = session_info.get("parameters", {})
   stop_name = parameters.get("stop_name", "")
   route = parameters.get("bus_route")
   stop_id = get_stop_point_id(stop_name)
   if not stop_id:
       return jsonify({
           "fulfillment_response": {
               "messages": [{"text": {"text": [f"Sorry, I couldn't find the stop '{stop_name}'"]}}]
           }
       })
   # Call TfL API to get arrivals
   params = {"app_id": TFL_APP_ID, "app_key": TFL_APP_KEY}
   arrivals_resp = requests.get(ARRIVALS_URL.format(stop_id), params=params, timeout=10)
   arrivals_resp.raise_for_status()
   arrivals_data = arrivals_resp.json()
   # Filter by route if provided
   if route:
       arrivals_data = [item for item in arrivals_data if item["lineName"] == route]
   # Sort and format the arrivals
   arrivals_data.sort(key=lambda x: x["timeToStation"])
   if not arrivals_data:
       text = f"No upcoming buses found at {stop_name}."
   else:
       parts = []
       now = datetime.now(timezone.utc)
       for item in arrivals_data[:3]:  # top 3
           line = item["lineName"]
           dest = item["destinationName"]
           time_to_arrival = item["timeToStation"] // 60
           time_str = "due" if time_to_arrival == 0 else f"in {time_to_arrival} minutes"
           parts.append(f"The {line} to {dest} is {time_str}")
       text = ". ".join(parts)
   return jsonify({
       "fulfillment_response": {
           "messages": [{"text": {"text": [text]}}]
       }
   })
