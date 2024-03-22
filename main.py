from datetime import datetime, timedelta
import os.path
import json
import logging, sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from notion_client import Client

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
logging.basicConfig(filename="debug.log", filemode='a')
with open("variables.json") as f:
    variables = json.load(f)
    ACCEPTED_CALENDARS = variables["calendars"]
    DATABASE_ID = variables["database_id"]
    NOTION_SECRET = variables["notion_secret"]

# Authenticate with Google Calendar API
def authenticate_google():
    credentials = None
    token_path = 'token.json'

    if os.path.exists(token_path):
        credentials = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES
            )
            credentials = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(credentials.to_json())

    return build('calendar', 'v3', credentials=credentials)

# Fetch Google Calendar Events
def fetch_google_events(service):
    color_mapping_path = "calendar.json"

    # Load color mapping from JSON file
    with open(color_mapping_path, 'r') as json_file:
        color_mapping = json.load(json_file)

    # Get the calendar list
    calendars = service.calendarList().list().execute().get('items', [])

    # Define the start and end dates for the recent week
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    logging.info(end_date, start_date)

    # Fetch events from each calendar within the recent week
    all_events = []
    for calendar in calendars:
        calendar_id = calendar['id']
        if calendar_id not in ACCEPTED_CALENDARS:
            continue

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=start_date.isoformat() + 'Z',
            timeMax=end_date.isoformat() + 'Z',
            orderBy='startTime',
            singleEvents = True
        ).execute().get('items', [])
        # out = open("test.json", "w")
        # json.dump(events, out)
        # out.close()

        for event in events:
            if event['status'] == "cancelled":
                continue
            # Extract relevant information
            start_time = event['start'].get('dateTime', event['start'].get('date'))
            end_time = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', 'No Title')
            color_id = event.get('colorId', "1")
            description = event.get('description', None)

            # Map color to item using the provided JSON file
            item = color_mapping.get(color_id, 'Uncategorized')

            # Convert time strings to datetime objects
            start_datetime = datetime.fromisoformat(start_time)
            end_datetime = datetime.fromisoformat(end_time)

            time_difference_seconds = (end_datetime - start_datetime).total_seconds()
            time = round(time_difference_seconds / 3600, 2)

            # Checks that not ongoing event
            if time < 24:
                event_details = {
                    'summary': summary,
                    'item': item,
                    'start_datetime': start_datetime,
                    'end_datetime': end_datetime,
                    'hours': time,
                    'color_id': color_id,
                    'description': description 
                }
                all_events.append(event_details)
    logging.info(all_events)
    return all_events

# Authenticate with Notion API
def authenticate_notion():
    # Use the Notion integration token for authentication
    return Client(auth=NOTION_SECRET)

# Insert Events into Notion Database
def insert_into_notion(client, events, calendar_mapping):        
    # Get last entry number
    temp_db = client.databases.query(
        **{
	        "database_id": DATABASE_ID,
	        "sorts": [
                {
                "property": "Entry Number",
                "direction": "descending"
                }
            ],
    	})
    last_entry_no = temp_db["results"][0]["properties"]["Entry Number"]["title"][0]["plain_text"]

    # Convert calendar information
    time_values = init_time_values(calendar_mapping)
    for event in events:
        color_id = event['color_id']
        try:
            type = calendar_mapping[color_id].get("type")
        except:
            Exception("Colours not mapped correctly.")
        time = event["hours"]
        time_values[type]["number"] += time
    
    # Set new values
    new_entry_dict = {}
    entry_dict = generate_entry_dict(int(last_entry_no))
    date_dict = generate_date_dict()
    new_entry_dict.update({"Entry Number": entry_dict})
    new_entry_dict.update({"Date": date_dict})
    new_entry_dict.update(time_values)

    # Import properties into new row
    client.pages.create(
        **{
            "parent": {"database_id": DATABASE_ID},
            "properties": new_entry_dict
        })
    return

def init_time_values(calendar_mapping):
    output_dict = {}
    for item in calendar_mapping.values():
        new_entry = {
            "type": "number",
            "number": 0
        }
        output_dict.update({item['type']: new_entry})

    return output_dict

def generate_date_dict():
    output_dict = {
        "type": "date",
        "date": {
            "start": datetime.today().strftime('%Y-%m-%d'),
            "end": None,
            "time_zone": None
        }
    }
    return output_dict

def generate_entry_dict(last_entry_no):
    output_dict = {
        "id": "title",
        "type": "title",
        "title": [
            {
                "type": "text",
                "text": {
                    "content": str(last_entry_no+1),
                    "link": None
                },
                "annotations": {
                    "bold": False,
                    "italic": False,
                    "strikethrough": False,
                    "underline": False,
                    "code": False,
                    "color": "default"
                },
                "plain_text": str(last_entry_no+1),
                "href": None
            }
        ]
    }
    return output_dict

# Main Script
if __name__ == '__main__':
    google_service = authenticate_google()
    notion_client = authenticate_notion()

    # Fetch events from Google Calendar
    events = fetch_google_events(google_service)

    # Insert events into Notion
    with open("calendar.json") as f:
        calendar_mapping = json.load(f)

    insert_into_notion(notion_client, events, calendar_mapping)
    
