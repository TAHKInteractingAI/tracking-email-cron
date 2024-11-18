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
            # "Content-Type": "multipart/form-data"
        }
        message = '{{"subject": \"{email_subject}\", "body": \"{email_message}\", "to": [{{"name": \"{name}\", "email": \"{email}\"}}], "reply_to": [{{"name": \"{name}\", "email": \"{email}\"}}], "tracking_options": {{"opens": true, "links": true, "thread_replies": false}}}}'.format(email_subject=email_subject, email_message=convert_links(email_message), name=row.get("Name"), email=email_to)

        files = {
            'message': (None, message),
        }
        for attachment_path in attachment_paths:
            # unique_id = uuid.uuid4().hex + "_" + str(pendulum.now().timestamp()) + "_" + str(encode_base64(attachment_path))
            unique_id = uuid.uuid4().hex + "_" + str(pendulum.now().timestamp())
            files[unique_id] = open(attachment_path, "rb")

        response = requests.post(url, headers=headers, files=files)
        payload = response.json()
        print(payload['data']['id'])

        df.at[index, 'Status'] = payload['data']['folders'][0]
        df.at[index, 'Tracking'] = payload['data']['folders'][0]
        df.at[index, 'Date'] = pendulum.from_timestamp(payload['data']['date'], tz="Asia/Ho_Chi_Minh").to_datetime_string()
        if index in empty_status_df_copy.index:
            empty_status_df_copy.at[index, 'Date'] = df.at[index, 'Date']
            empty_status_df_copy.at[index, 'Message ID'] = payload['data']['id']
        time.sleep(5)
empty_status_df_copy.reset_index(drop=True, inplace=True)
df_1 = pd.concat([df_1, empty_status_df_copy], ignore_index=True).drop_duplicates(subset=['Name', 'Email'], keep='last')
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
            params={"dir": "asc", **({"next": next_cursor} if next_cursor is not None else {})}
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

    while True:
        messages = nylas.messages.list(GRANT_ID,
            query_params={"limit": 10, **({"page_token": next_cursor} if next_cursor is not None else {}), "select": "grant_id,from,object,id,thread_id,subject,snippet,to,bcc,cc,reply_to,attachments,folders,headers,unread,starred,created_at,date,schedule_id,send_at", "from": EMAIL, "in": "SENT", "received_after": pendulum.parse(df_1.loc[0, 'Date'], tz="Asia/Ho_Chi_Minh").int_timestamp}
        )
        time.sleep(2)

        message_list.append(messages)

        if hasattr(messages, 'next_cursor') and messages.next_cursor:
            next_cursor = messages.next_cursor
            yield next_cursor
            time.sleep(2)
        else:
            time.sleep(2)
            break

message_generators = pagination_message()
for generator in message_generators:
    print(generator)
flatten_message_list = list(itertools.chain.from_iterable(message.data for message in message_list))
filter_flatten_message_list = [sent_message for index, row in df_1.iterrows() for sent_message in flatten_message_list if row['Email'] == sent_message.to[0]['email'] and row['Message ID'] == sent_message.id]
print('TRACKED MESSAGE')

email_list, track_list, email_track_dict = [], [], {}
for flatten_payload_model in flatten_payload_model_list_final:
    try:
        response_id = requests.get(f"https://api.hookdeck.com/2024-09-01/requests/{flatten_payload_model['id']}", headers={
        "Authorization": f"Bearer {API_KEY_WEBHOOK_URL}",
        "Content-Type": "application/json"
        })
        payload_id = response_id.json()
        time.sleep(2)

        for index, message in enumerate(filter_flatten_message_list):
            if payload_id['data']['body']['data']['object']['message_id'] == message.id:
                if len(list(df.loc[df['Email'] == message.to[0]['email'], 'Tracking'])[0].split(', ')) == 3:
                    continue
                elif len(list(df.loc[df['Email'] == message.to[0]['email'], 'Tracking'])[0].split(', ')) == 2:
                    if payload_id['data']['body']['type'] == 'message.link_clicked':
                        email_list.append(message.to[0]['email'])
                        track_list.append('CLICKED')
                elif len(list(df.loc[df['Email'] == message.to[0]['email'], 'Tracking'])[0].split(', ')) == 1:
                    email_list.append(message.to[0]['email'])
                    if payload_id['data']['body']['type'] == 'message.opened':
                        track_list.append('OPENED')
                    elif payload_id['data']['body']['type'] == 'message.link_clicked':
                        track_list.append('CLICKED')
                # else:
                #     df.loc[df['Email'] == message.to[0]['email'], 'Tracking'] = "SENT"
                #     email_list.append(message.to[0]['email'])
                #     if payload_id['data']['body']['type'] == 'message.opened':
                #         track_list.append('OPENED')
                #     elif payload_id['data']['body']['type'] == 'message.link_clicked':
                #         track_list.append('CLICKED')
                break
        time.sleep(2)
    except:
        print(flatten_payload_model['id'])
        time.sleep(2)
print('INVOKED INCOMING REQUESTS FROM WEBHOOK URL AND ADDED TRACKING STATUS TRIGGERED FROM NYLAS')

for index, row in df.iterrows():
    try:
        for email, track in zip(email_list, track_list):
            if email not in email_track_dict:
                email_track_dict[email] = {'email': email, 'status': []}
            email_track_dict[email]['status'].append(track)

        email_track_list = list(email_track_dict.values())
        email_track_list_final = [{'email': email_track['email'], 'status': list(set(email_track['status']))} for email_track in email_track_list]

        for email_track in email_track_list_final:
            if df.loc[index, 'Email'] == email_track['email']:
                df.loc[index, 'Tracking'] += ', ' + ', '.join(email_track['status'])
                duplicated_tracking = df.loc[index, 'Tracking']
                deduplicated_tracking = ', '.join(dict.fromkeys(duplicated_tracking.split(', ')))
                df.loc[index, 'Tracking'] = deduplicated_tracking

        # UPDATE GOOGLE SHEET DATA.
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
    except:
        print(f"All recipients have not opened or clicked the link of the email yet")
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
        break
print('UPDATED GOOGLE SHEET DATA')
