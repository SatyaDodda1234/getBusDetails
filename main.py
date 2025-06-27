import os
import requests
import functions_framework
from datetime import datetime, timezone

TFL_APP_ID  = os.getenv("TFL_APP_ID")   
TFL_APP_KEY = os.getenv("TFL_APP_KEY")
SEARCH_URL  = "https://api.tfl.gov.uk/StopPoint/Search/{}"
ARRIVAL_URL = "https://api.tfl.gov.uk/StopPoint/{}/Arrivals"
def get_stop_point_id(stop_name: str) -> str | None:
   """Return the first StopPoint ID that TfL search deems most relevant."""
   params = {"app_id": TFL_APP_ID, "app_key": TFL_APP_KEY}
   resp   = requests.get(SEARCH_URL.format(stop_name), params=params, timeout=10)
   resp.raise_for_status()
   matches = resp.json().get("matches", [])
   if not matches:
       return None
   # Highest-ranking match’s id
   return matches[0]["id"]   # e.g. "490009224S"
# ---------------------------------------------------------------------------
# ❷  Helper – fetch & format arrival data
# ---------------------------------------------------------------------------
def build_arrival_message(stop_id: str, route: str | None = None) -> str:
   params = {"app_id": TFL_APP_ID, "app_key": TFL_APP_KEY}
   resp   = requests.get(ARRIVAL_URL.format(stop_id), params=params, timeout=10)
   resp.raise_for_status()
   arrivals = resp.json()
   if route:
       arrivals = [a for a in arrivals if a["lineName"] == route]
   if not arrivals:
       return "I couldn't find any upcoming buses for that stop right now."
   # soonest first
   arrivals.sort(key=lambda a: a["timeToStation"])
   sentences = []
   now_utc = datetime.now(timezone.utc)
   for a in arrivals[:3]:                       # limit to three lines to keep it short
       mins = round(a["timeToStation"] / 60)
       when = "due" if mins <= 0 else f"in {mins} min"
       line = a["lineName"]
       dest = a["destinationName"].split(",")[0]  # remove extra commas TfL sometimes adds
       sentences.append(f"The {line} to {dest} is {when}.")
   return " ".join(sentences)
# ---------------------------------------------------------------------------
# ❸  Dialogflow CX webhook entry-point
# ---------------------------------------------------------------------------
@functions_framework.http
def london_transit_handler(request):
   req_json = request.get_json(silent=True) or {}
   params   = req_json.get("sessionInfo", {}).get("parameters", {})
   stop_name = params.get("stop_name")
   if not stop_name:
       return _df_response("Which stop are you interested in?")
   stop_id = get_stop_point_id(stop_name)
   if not stop_id:
       return _df_response(
           f"I couldn't find a TfL stop called “{stop_name}”. "
           "Could you re-check the name?"
       )
   bus_route = params.get("bus_route")  # may be None
   try:
       answer = build_arrival_message(stop_id, bus_route)
   except requests.HTTPError:
       answer = "TfL's live data service is unavailable right now. Please try again later."
   return _df_response(answer)
# ---------------------------------------------------------------------------
# ❹  Utility – build Dialogflow CX response JSON
# ---------------------------------------------------------------------------
def _df_response(text: str):
   return {
       "fulfillment_response": {
           "messages": [
               {
                   "text": {
                       "text": [text]
                   }
               }
           ]
       }
   }
