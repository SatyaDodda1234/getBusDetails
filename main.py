import functions_framework
import json
import os
import requests
from datetime import datetime, timedelta

# --- Configuration (Replace with your actual keys) ---
# It's better to use environment variables for sensitive info in production
TFL_APP_ID = os.environ.get('TFL_APP_ID', 'YOUR_TFL_APP_ID') # Replace with your TfL App ID
TFL_APP_KEY = os.environ.get('TFL_APP_KEY', 'YOUR_TFL_APP_KEY') # Replace with your TfL App Key
TFL_API_BASE_URL = "https://api.tfl.gov.uk"

# --- Helper Function for Stop ID Mapping ---
def get_stop_point_id(stop_input):
    stop_map = {
        "canary wharf": "490008660N",        # Canary Wharf Station / Poplar River (Bus Stop N)
        "london bridge": "490009224S",       # London Bridge Station / Borough High St (Stop S)
        "trafalgar square": "490007804S",    # Trafalgar Sq / Charing Cross Stn (Bus Stop P)
        "waterloo station": "9400ZZLUWLO",   # Waterloo Underground Station (Tube)
        "victoria station": "9400ZZLUVIC",   # Victoria Underground Station (Tube)
        "paddington station": "9400ZZLUPAC", # Paddington Underground Station (Tube)
        "green park": "9400ZZLUGPK",         # Green Park Underground Station (Tube)
        "kings cross": "9400ZZLUKGN",        # King's Cross St. Pancras Underground Station (Tube)
        "liverpool street": "9400ZZLULST",   # Liverpool Street Underground Station (Tube)
        "stratford": "9400ZZLUSTD",          # Stratford Underground Station (Tube)
        "euston station": "9400ZZLUEUS",     # Euston Underground Station (Tube)
        # Add more mappings as needed (Bus Stop ID, Tube Station ID, DLR ID etc.)
        # You can find TfL Stop IDs using their API or specific tools.
    }
    
    # Try to match direct ID if provided (e.g., "490007804S")
    if stop_input and stop_input.isdigit() and len(stop_input) in [5, 9]: # Basic check for common ID lengths
        # This is a simplification; a more robust solution would validate against TfL's actual ID format
        return stop_input 

    # Normalize input for map lookup
    normalized_input = stop_input.lower().strip() if stop_input else ""
    return stop_map.get(normalized_input)

# --- Main Webhook Handler ---
@functions_framework.http
def hello_http(request):
    request_json = request.get_json(silent=True)
    print(f"Dialogflow CX Request: {json.dumps(request_json, indent=2)}")

    intent_tag = request_json['fulfillmentInfo']['tag']
    parameters = request_json['sessionInfo']['parameters']

    response_text = "I'm sorry, I couldn't get the transit information right now. Please try again later."
    webhook_response = {
        "fulfillmentResponse": {
            "messages": [
                {
                    "text": {
                        "text": [response_text]
                    }
                }
            ]
        }
    }

    if intent_tag == "GetTransitSchedule":
        # Extract parameters. destination is not expected, so it will be None.
        bus_route = parameters.get('bus_route', {}).get('resolvedValue')
        stop_name = parameters.get('stop_name', {}).get('resolvedValue') 

        print(f"Extracted parameters: BusRoute='{bus_route}', StopName='{stop_name}'")

        target_stop_id = None
        if stop_name:
            target_stop_id = get_stop_point_id(stop_name)
            if not target_stop_id:
                print(f"Warning: Could not map stop_name '{stop_name}' to a TfL StopPoint ID.")
        
        if not target_stop_id:
            response_text = "I couldn't identify the specific stop or station you're asking about. Could you please provide a well-known stop name, landmark, or a TfL Stop ID?"
            webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
            return json.dumps(webhook_response)

        try:
            # Construct TfL API URL
            tfl_url = f"{TFL_API_BASE_URL}/StopPoint/{target_stop_id}/Arrivals"
            params = {
                "app_id": TFL_APP_ID,
                "app_key": TFL_APP_KEY
            }

            print(f"Calling TfL API: {tfl_url} with params {params}")
            tfl_response = requests.get(tfl_url, params=params, timeout=10)
            tfl_response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            arrivals_data = tfl_response.json()
            print(f"TfL API Response (partial): {arrivals_data[:2]}") # Print first 2 arrivals for brevity

            # Sort arrivals by expected arrival time
            arrivals_data.sort(key=lambda x: x.get('expectedArrival', '9999-12-31T23:59:59Z'))

            if arrivals_data:
                filtered_arrivals = arrivals_data 
                if bus_route:
                    search_route = str(bus_route).lower().strip()
                    filtered_arrivals = [
                        a for a in arrivals_data
                        if search_route == a.get('lineName', '').lower().strip()
                        or search_route == a.get('lineId', '').lower().strip()
                    ]
                    
                    if not filtered_arrivals:
                        response_text = f"I couldn't find any upcoming arrivals for route '{bus_route}' at this stop. It might not serve this stop, or there are no immediate arrivals."
                        webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
                        return json.dumps(webhook_response)
                        
                if filtered_arrivals:
                    message_parts = []
                    # Limit to top 3 relevant arrivals for a concise response
                    for arrival in filtered_arrivals[:3]:
                        line_name = arrival.get('lineName', 'N/A')
                        destination_name = arrival.get('destinationNaptanId', 'N/A') # Or 'towards'
                        # Look up destination from TfL API if NaptanId is available
                        # For simplicity, we'll just use 'towards' or a common name
                        
                        # Get minutes until arrival
                        expected_arrival_utc = datetime.fromisoformat(arrival['expectedArrival'].replace('Z', '+00:00'))
                        time_difference = expected_arrival_utc - datetime.now(expected_arrival_utc.tzinfo)
                        minutes = int(time_difference.total_seconds() / 60)

                        if minutes < 1:
                            minutes_str = "due"
                        elif minutes == 1:
                            minutes_str = "1 minute"
                        else:
                            minutes_str = f"{minutes} minutes"
                        
                        # Use 'destinationName' if available, otherwise 'towards' for bus destinations
                        # For Tube, 'destinationName' is usually the final station.
                        display_destination = arrival.get('destinationName') or arrival.get('towards')
                        
                        # Adjust message for Tube/DLR vs Bus
                        if arrival.get('modeName', '').lower() in ['tube', 'dlr', 'overground', 'elizabeth-line']:
                            message_parts.append(f"The {line_name} to {display_destination} is in {minutes_str}.")
                        else: # Assuming bus or other
                             message_parts.append(f"The {line_name} to {display_destination} is in {minutes_str}.")
                        
                    response_text = "\n".join(message_parts)
                    webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
                else:
                    response_text = "I couldn't find any upcoming arrivals at this stop right now."
                    webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
            else:
                response_text = "No arrival information available for this stop at the moment."
                webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]

        except requests.exceptions.HTTPError as err:
            print(f"HTTP error occurred: {err} - Response: {err.response.text}")
            response_text = "I'm having trouble connecting to the transit service. Please try again in a moment."
            webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
        except requests.exceptions.ConnectionError as err:
            print(f"Connection error occurred: {err}")
            response_text = "I can't reach the transit service. Please check your internet connection or try again later."
            webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
        except requests.exceptions.Timeout as err:
            print(f"Timeout error occurred: {err}")
            response_text = "The transit service took too long to respond. Please try again."
            webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]
        except Exception as err:
            print(f"An unexpected error occurred: {err}")
            response_text = "Something went wrong while fetching transit info. Please try again."
            webhook_response["fulfillmentResponse"]["messages"][0]["text"]["text"] = [response_text]

    return json.dumps(webhook_response)
