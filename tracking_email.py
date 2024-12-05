from __future__ import print_function
from googleapiclient.discovery import build 
from google.oauth2 import service_account
import pandas as pd
import os
import time
from nylas import Client
from nylas.models.webhooks import CreateWebhookRequest
from nylas.models.webhooks import WebhookTriggers
import pendulum
import requests
import re
import uuid
import itertools
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
credentials = service_account.Credentials.from_service_account_info({
  "type": os.getenv('TYPE'),
  "project_id": os.getenv('PROJECT_ID'),
  "private_key_id": os.getenv('PRIVATE_KEY_ID'),
  "private_key": os.getenv('PRIVATE_KEY').replace("\\n", "\n"),
  "client_email": os.getenv('CLIENT_EMAIL'),
  "client_id": os.getenv('CLIENT_ID'),
  "auth_uri": os.getenv('AUTH_URI'),
  "token_uri": os.getenv('TOKEN_URI'),
  "auth_provider_x509_cert_url": os.getenv('AUTH_PROVIDER_CERT_URL'),
  "client_x509_cert_url": os.getenv('CLIENT_CERT_URL'),
  "universe_domain": os.getenv('UNIVERSE_DOMAIN')
})
spreadsheet_service = build('sheets', 'v4', credentials=credentials)

SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
RANGE_NAME = 'tracking_email'
sheet = spreadsheet_service.spreadsheets()
result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
values = result.get('values', [])
max_cols = max(len(row) for row in values)
values = [row + [''] * (max_cols - len(row)) for row in values]
df = pd.DataFrame(values[1:], columns=values[0])
df = df.fillna('')
# df.head()

RANGE_NAME_1 = 'sending_email'
sheet_1 = spreadsheet_service.spreadsheets()
result_1 = sheet_1.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME_1).execute()
values_1 = result_1.get('values', [])
max_cols_1 = max(len(row) for row in values_1)
values_1 = [row + [''] * (max_cols_1 - len(row)) for row in values_1]
df_1 = pd.DataFrame(values_1[1:], columns=values_1[0])
df_1 = df_1.fillna('')
# df_1.head()
print('CONNECTED TO GOOGLE SHEET')

API_KEY = os.getenv('API_KEY')
GRANT_ID = os.getenv('GRANT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
EMAIL = os.getenv('EMAIL')
API_URI = os.getenv('API_URI')
API_KEY_WEBHOOK_URL = os.getenv('API_KEY_WEBHOOK_URL')

nylas = Client(
    API_KEY
)

webhooks = nylas.webhooks.list()
webhook_url_list = []

for webhook in webhooks.data:
    if webhook.status == 'active':
        webhook_url_list.append(webhook.webhook_url)

if WEBHOOK_URL not in webhook_url_list:
    webhook = nylas.webhooks.create(
      request_body={
        "trigger_types": [WebhookTriggers.MESSAGE_OPENED, WebhookTriggers.MESSAGE_LINK_CLICKED],
        "webhook_url": WEBHOOK_URL,
        "description": "track-email",
        "notification_email_address": EMAIL,
      }
    )
print('CONNECTED TO NYLAS AND INTEGRATED WEBHOOK')

empty_status_df_copy = df.loc[df['Status'] == ''].copy()
def convert_links(html):
    pattern = r'<a href="([^"]+)">([^<]+)</a>'

    def replacement(match):
        url = match.group(1)
        return f"<a href=\'{url}\'>{url}</a>"

    modified_html = re.sub(pattern, replacement, html)
    return modified_html

for index, row in df.loc[df['Status'] == ''].iterrows():
    email_to = str(row['Email']).strip()
    if '@' in email_to and '.' in email_to.split('@')[1]:
        email_subject = row.get('Title', 'No Subject')
        email_message = row.get('Content', '').replace('{{name}}', row.get('Name', '')).replace('\n', '')
        attachment_paths = row.get('Attachment1', '').split(', ') if pd.notna(row.get('Attachment1')) else []

        url = f"https://api.us.nylas.com/v3/grants/{GRANT_ID}/messages/send"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Accept-Encoding": "gzip"
            # "Content-Type": "multipart/form-data"
        }
        message = '{{"subject": \"{email_subject}\", "body": \"{email_message}\", "to": [{{"name": \"{name}\", "email": \"{email}\"}}], "reply_to": [{{"name": \"{name}\", "email": \"{email}\"}}], "tracking_options": {{"opens": true, "links": true, "thread_replies": true, "label": "{label}\"}}, "send_at": {email_send_at}}}'.format(email_subject=email_subject, email_message=convert_links(email_message), name=row.get("Name"), email=email_to, email_send_at=pendulum.now().add(minutes=2).int_timestamp, label=pendulum.now().int_timestamp)

        files = {
            'message': (None, message),
        }
        for attachment_path in attachment_paths:
            # unique_id = uuid.uuid4().hex + "_" + str(pendulum.now().timestamp()) + "_" + str(encode_base64(attachment_path))
            unique_id = uuid.uuid4().hex + "_" + str(pendulum.now().timestamp())
            files[unique_id] = open(attachment_path, "rb")

        response = requests.post(url, headers=headers, files=files)
        payload = response.json()
        print(payload['data']['schedule_id'])

        df.at[index, 'Status'] = 'SENT'
        df.at[index, 'Tracking'] = 'SENT'
        df.at[index, 'Date'] = pendulum.from_timestamp(int(payload['data']['tracking_options']['label']), tz="Asia/Ho_Chi_Minh").to_datetime_string()
        if index in empty_status_df_copy.index:
            empty_status_df_copy.at[index, 'Title'] = payload['data']['subject']
            empty_status_df_copy.at[index, 'Content'] = payload['data']['body']
            empty_status_df_copy.at[index, 'Schedule ID'] = payload['data']['schedule_id']
            empty_status_df_copy.at[index, 'Schedule Date'] = pendulum.from_timestamp(payload['data']['send_at'], tz="Asia/Ho_Chi_Minh").to_datetime_string()
            empty_status_df_copy.at[index, 'Date'] = df.at[index, 'Date']
        time.sleep(5)
empty_status_df_copy.reset_index(drop=True, inplace=True)
df_1 = pd.concat([df_1, empty_status_df_copy], ignore_index=True).drop_duplicates(subset=['Name', 'Title', 'Content', 'Email'], keep='last').fillna('')
df_1.reset_index(drop=True, inplace=True)
df_1.drop(columns=['Status', 'Merge status', 'Tracking'], inplace=True)
print('SENT MESSAGES TO THE SPECIFIC EMAILS')

def pagination_tracking():
    next_cursor = yield
    global payload_model_list
    payload_model_list = []

    while True:
        response = requests.get("https://api.hookdeck.com/2024-09-01/requests",
            headers={
                "Authorization": f"Bearer {API_KEY_WEBHOOK_URL}",
                "Content-Type": "application/json"
            },
            params={"dir": "desc", **({"next": next_cursor} if next_cursor is not None else {})}
        )
        payload = response.json()
        time.sleep(2)

        payload_model_list.append(payload['models'])

        if 'next' in payload.get('pagination', {}):
            next_cursor = payload['pagination']['next']
            yield next_cursor
            time.sleep(2)
        else:
            time.sleep(2)
            break

generators = pagination_tracking()
for generator in generators:
    print(generator)
print('TRACKED PAGINATION')

flatten_payload_model_list = list(itertools.chain(*payload_model_list))
for flatten_payload_model in flatten_payload_model_list:
    for date_field in ['created_at', 'updated_at', 'ingested_at']:
        if date_field in flatten_payload_model:
            flatten_payload_model[date_field] = pendulum.parse(flatten_payload_model[date_field]).in_tz("Asia/Ho_Chi_Minh").to_datetime_string()
print('FLATTENED MODEL LIST')

flatten_unique_payload_models = {}

for flatten_payload_model in flatten_payload_model_list:
    created_at = flatten_payload_model['created_at']
    if created_at not in flatten_unique_payload_models:
        flatten_unique_payload_models[created_at] = flatten_payload_model

flatten_payload_model_list_final = list(flatten_unique_payload_models.values())
print('FILTERED MODEL LIST BASED ON CREATED DATE')

def pagination_message():
    next_cursor = yield
    global message_list
    message_list = []

    messages = nylas.messages.list_scheduled_messages(GRANT_ID)
    time.sleep(5)
    message_list.append(messages)

message_generators = pagination_message()
for generator in message_generators:
    print(generator)
flatten_message_list = list(itertools.chain.from_iterable(message.data for message in message_list))
filter_flatten_message_list = [sent_message for index, row in df_1.iterrows() for sent_message in flatten_message_list if row['Schedule ID'] == sent_message.schedule_id]
filter_flatten_message_list_final = list(itertools.filterfalse(lambda message: message.schedule_id not in set(df_1.loc[df_1['Date'].isin(df['Date']), 'Schedule ID'].values), filter_flatten_message_list))
print('TRACKED MESSAGE')

email_list, track_list, email_track_dict, email_message_id_list = [], [], {}, []
for flatten_payload_model in flatten_payload_model_list_final:
    try:
        response_id = requests.get(f"https://api.hookdeck.com/2024-09-01/requests/{flatten_payload_model['id']}", headers={
            "Authorization": f"Bearer {API_KEY_WEBHOOK_URL}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip"
        })
        payload_id = response_id.json()

        for index, message in enumerate(filter_flatten_message_list_final):
            if payload_id['data']['body']['data']['object']['schedule_id'] == message.schedule_id and df_1.loc[df_1['Date'].isin(df['Date']), 'Schedule ID'].values[index] == message.schedule_id:
                if len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 1:
                    if payload_id['data']['body']['type'] == 'message.send_success':
                        df['Tracking'] = df['Tracking'].mask(df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'SENT SUCCESS')
                        df_1['Message ID'] = df_1['Message ID'].mask((df_1['Schedule ID'] == payload_id['data']['body']['data']['object']['schedule_id']) & (df_1['Schedule Date'] == pendulum.from_timestamp(payload_id['data']['body']['data']['object']['send_at'], tz="Asia/Ho_Chi_Minh").to_datetime_string()), payload_id['data']['body']['data']['object']['id'])
                    elif payload_id['data']['body']['type'] == 'message.send_failed':
                        df['Tracking'] = df['Tracking'].mask(df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'SENT FAILED')
        time.sleep(2)
    except:
        print(flatten_payload_model['id'])

for flatten_payload_model in flatten_payload_model_list_final:
    try:
        response_id = requests.get(f"https://api.hookdeck.com/2024-09-01/requests/{flatten_payload_model['id']}", headers={
            "Authorization": f"Bearer {API_KEY_WEBHOOK_URL}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip"
        })
        payload_id = response_id.json()
        for index, message in enumerate(filter_flatten_message_list_final):
            if payload_id['data']['body']['data']['object']['message_id'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Message ID'].values[index]:
                if len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 4:
                    continue
                elif len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 3:
                    if payload_id['data']['body']['type'] == 'message.link_clicked' and 'LINK CLICKED' not in df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ') and 'THREAD REPLIED' in df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', '):
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['message_id'] )
                        track_list.append('LINK CLICKED')
                elif len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 2:
                    if payload_id['data']['body']['type'] == 'message.link_clicked':
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['message_id'] )
                        track_list.append('LINK CLICKED')
                elif len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 1:
                    if payload_id['data']['body']['type'] == 'message.opened':
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['message_id'] )
                        track_list.append('OPENED')
                    elif payload_id['data']['body']['type'] == 'message.bounce_detected':
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['message_id'] )
                        track_list.append('BOUNCE DETECTED')
        time.sleep(2)
    except:
        print(flatten_payload_model['id'])

for flatten_payload_model in flatten_payload_model_list_final:
    try:
        response_id = requests.get(f"https://api.hookdeck.com/2024-09-01/requests/{flatten_payload_model['id']}", headers={
            "Authorization": f"Bearer {API_KEY_WEBHOOK_URL}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip"
        })
        payload_id = response_id.json()
        for index, message in enumerate(filter_flatten_message_list_final):
            if payload_id['data']['body']['data']['object']['root_message_id'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Message ID'].values[index]:
                if len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 4:
                    continue
                elif len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 3:
                    if payload_id['data']['body']['type'] == 'thread.replied' and 'THREAD REPLIED' not in df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ') and 'LINK CLICKED' in df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', '):
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['root_message_id'] )
                        track_list.append('THREAD REPLIED')
                elif len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 2:
                    if payload_id['data']['body']['type'] == 'thread.replied':
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['root_message_id'] )
                        track_list.append('THREAD REPLIED')
                elif len(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Tracking'].values[0].split(', ')) == 1:
                    if payload_id['data']['body']['type'] == 'message.opened':
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['message_id'] )
                        track_list.append('OPENED')
                    elif payload_id['data']['body']['type'] == 'message.bounce_detected':
                        email_list.append(df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[index], 'Email'].values[0])
                        email_message_id_list.append(payload_id['data']['body']['data']['object']['message_id'] )
                        track_list.append('BOUNCE DETECTED')
        time.sleep(2)
    except:
        print(flatten_payload_model['id'])
print('INVOKED INCOMING REQUESTS FROM WEBHOOK URL AND ADDED TRACKING STATUS TRIGGERED FROM NYLAS')

print(list(zip(email_list, track_list, email_message_id_list)))

def update_status():
    global status_dict
    status_dict = defaultdict(set)
    yield from enumerate(zip(email_list, track_list, email_message_id_list))

status_generators = update_status()
for index, generator in status_generators:
    email, *track, message_id = generator
    status_dict[(email, message_id)].update(track)

def update_status_final():
    yield from enumerate(status_dict.items())

status_final_generators = update_status_final()
for index, generator in status_final_generators:
    (email, message_id), track = generator
    for _index, row in df_1.iterrows():
        try:
            if df_1.loc[df_1['Date'].isin(df['Date']), 'Message ID'].values[_index] == message_id:
              df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[_index], 'Tracking'] += ', ' + ', '.join(list(track))
              duplicated_tracking = df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[_index], 'Tracking']
              deduplicated_tracking = ', '.join(dict.fromkeys(duplicated_tracking.split(', ')))
              df.loc[df['Date'] == df_1.loc[df_1['Date'].isin(df['Date']), 'Date'].values[_index], 'Tracking'] = deduplicated_tracking
        except:
            pass

updated_values = [df.columns.tolist()] + df.values.tolist()
body = {'values': updated_values}
result = spreadsheet_service.spreadsheets().values().update(
    spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME,
    valueInputOption='RAW', body=body).execute()

updated_values_1 = [df_1.columns.tolist()] + df_1.values.tolist()
body_1 = {'values': updated_values_1}
result_1 = spreadsheet_service.spreadsheets().values().update(
    spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME_1,
    valueInputOption='RAW', body=body_1).execute()
print('UPDATED GOOGLE SHEET DATA')
