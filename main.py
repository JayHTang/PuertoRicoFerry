import json
import logging
import os
import smtplib
import ssl
import sys
from typing import Dict, List

import dotenv
import requests

dotenv.load_dotenv()
SENDER = os.environ['SENDER']
PASSWORD = os.environ['PASSWORD']
RECIPIENTS = [r.strip() for r in os.environ['RECIPIENTS'].split(';') if r.strip()]
URL = r'https://my.hornblower.com/graphql'
DATE_FILE = "sent_dates.txt"

headers = {
    'Content-Type': 'application/json',
}

stops_variables = {
    "propertyId": "hpurico",
    "bookingType": 1,
    "date": "03/30/2022",
    "correlationId": "7c2b52cd-0535-40f4-90bb-e78e952ea9c9",
}

stops_query = """
query ticketAvailabilityV2(
  $propertyId: String!
  $bookingType: String!
  $date: String!
  $correlationId: String!
) { 
  ticketAvailabilityV2(
    propertyId: $propertyId
    bookingType: $bookingType
    date: $date
    correlationId: $correlationId
  ) {
    stops(propertyId: $propertyId, correlationId: $correlationId) {
      id
      name
      stopNumber
    }
  }
}
"""

avail_variables = {
    "propertyId": "hpurico",
    "bookingType": 1,
    "date": "04/13/2022",
    "correlationId": "7c2b52cd-0535-40f4-90bb-e78e952ea9c9",
    "costRateId": 1,
    "source": "web",
    "withPricelistTemplates": False,
    "withTicketsDataHash": True,
    "withVacancies": True,
    "skipFiltersForPastTransfers": False,
    "editOrder": False,
    "requiredQty": 0,
    "usePriceBand": False,
    "withAttendeeDetails": False
}

avail_query = """
query ticketAvailabilityV2(
  $propertyId: String!
  $bookingType: String!
  $date: String!
  $correlationId: String!
  $costRateId: Int
  $token: String
  $source: String
  $tourEventId: Int
  $tourEventIds: [Int]
  $withTicketsDataHash: Boolean!
  $withVacancies: Boolean!
  $skipFiltersForPastTransfers: Boolean
  $editOrder: Boolean
  $requiredQty: Int
  $usePriceBand: Boolean
) { 
  ticketAvailabilityV2(
    propertyId: $propertyId
    bookingType: $bookingType
    date: $date
    correlationId: $correlationId
    costRateId: $costRateId
    token: $token
    source: $source
    tourEventId: $tourEventId
    tourEventIds: $tourEventIds
    withTicketsDataHash: $withTicketsDataHash
    skipFiltersForPastTransfers: $skipFiltersForPastTransfers
    editOrder: $editOrder
    requiredQty: $requiredQty
    usePriceBand: $usePriceBand
  ) {
    ticketAvailability {
      costRateId
      vacancies @include(if: $withVacancies)
      note
      accountingFreeze
      BookingTypeId
      BookingTypeDescription
      TimedTicketTypeId
      TimedTicketTypeDescription
      StartDate
      StartTime
      EndTime
      boardingTime
      vacancy
      onHold
      Capacity
      pricing
      fromStopId
      toStopId
      numberOfStop
      duration
      eventStatus
      peakHours
      eventRank
      tourResources(propertyId: $propertyId, correlationId: $correlationId) {
        ResourceName
        vesselId
        vessel(propertyId: $propertyId) {
          details {
            id
            value
          }
        }
        vesselName
      }
    }
  }
}
"""


def is_email_sent(date):
    if not os.path.exists(DATE_FILE):
        with open(DATE_FILE, 'w') as f:
            pass  # make an empty file
    with open(DATE_FILE, 'r+') as f:
        dates = f.read()
        if date in dates:
            return True
        f.write(f'{date}\n')
        return False


def send_email(recipients: List[str], message: str, subject: str = ""):
    port = 465
    smtp_server = "smtp.gmail.com"

    if not message.startswith('Subject:'):
        message = f'Subject: {subject}\n\n{message}'
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
            server.login(SENDER, PASSWORD)
            for recipient in recipients:
                server.sendmail(SENDER, recipient, message)
    except Exception as e:
        logging.error(f"Failed to send email to {recipient} with message {message}")
        logging.error(e)


def query_stops(use_hard_coded: bool = True) -> Dict[int, str]:
    if use_hard_coded:
        return {
            721: "Vieques",
            722: "Culebra",
            723: "Ceiba",
        }

    stops_data = {
        "operationName": "ticketAvailabilityV2",
        "variables": stops_variables,
        "query": stops_query,
    }

    stops_json = requests.post(url=URL, headers=headers, json=stops_data).json()
    stops = {}
    for stop in stops_json["data"]["ticketAvailabilityV2"]["stops"]:
        stops[stop["id"]] = stop["name"]
    return stops


def query_tickets(date: str) -> str:
    stops = query_stops()

    if date:
        avail_variables["date"] = date

    avail_data = {
        "operationName": "ticketAvailabilityV2",
        "variables": avail_variables,
        "query": avail_query,
    }

    response = requests.post(url=URL, headers=headers, json=avail_data)
    notify = False
    if response.status_code == 200:
        avail_json = response.json()
        if avail_json["data"]["ticketAvailabilityV2"]["ticketAvailability"]:
            avails = {}
            for availability in avail_json["data"]["ticketAvailabilityV2"]["ticketAvailability"]:
                from_ = stops[availability["fromStopId"]]
                to = stops[availability["toStopId"]]
                key = f'{from_}-{to}-{availability["StartTime"] if len(availability["StartTime"]) == 8 else "0" + availability["StartTime"]}'
                for detail in availability['tourResources'][0]['vessel']['details']:
                    if detail['id'] == 'vesselType':
                        availability['vesselType'] = detail['value']
                avails[key] = availability

            tickets = []
            for avail, detail in avails.items():
                if detail['vesselType'] != 'cargoOnly':
                    vacancies = json.loads(detail['vacancies'])
                    available = vacancies['vacancy6497']
                    total = available - vacancies.get('vacancyPublic6497', 0)
                    tickets.append(f"\t{avail}: {available if available > 0 else 0:3} tickets remaining")

            tickets.sort()
            text = ''
            for i in range(len(tickets)):
                if i > 0 and tickets[i][:10] != tickets[i - 1][:10]:
                    text += '\n' + '-' * 53
                text += f'\n{tickets[i]}'

            notify = True
        else:
            text = f"No tickets available for {date} {str(avail_json)}"
    else:
        text = f"HTTP {response.status_code}: {str(response)}"

    if notify:
        if is_email_sent(date):
            logging.info(f'Email already sent for {date}')
        else:
            send_email(RECIPIENTS, text, f"Ferry available on {date}")

    return text


if __name__ == '__main__':
    logging.basicConfig(filename='puerto_rico_log.txt', format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info(query_tickets(sys.argv[1]))
