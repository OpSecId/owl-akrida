from .base import BaseVerifier
import json
import os
import requests
import time
from models import (
    RequestPresentationV2 as RequestPresentation, 
    ProofRequest, 
    AnonCredsPresReq
)
from settings import Settings

from json.decoder import JSONDecodeError


class AcapyVerifier(BaseVerifier):
    def __init__(self):
        self.label = "Test Verifier"
        self.filter = Settings.FILTER_TYPE
        self.agent_url = Settings.VERIFIER_URL
        self.headers = Settings.VERIFIER_HEADERS | {"Content-Type": "application/json"}

        self.cred_attributes = Settings.CRED_ATTR
        self.verifiedTimeoutSeconds = Settings.VERIFIED_TIMEOUT_SECONDS

    def get_invite(self):
        r = requests.post(
            f"{self.agent_url}/out-of-band/create-invitation?auto_accept=true",
            headers=self.headers,
            json={"handshake_protocols": ["https://didcomm.org/didexchange/1.0"]},
        )
        invitation = r.json()

        r = requests.get(
            f"{self.agent_url}/connections",
            headers=self.headers,
            params={"invitation_msg_id": invitation["invi_msg_id"]},
        )
        connections = r.json()

        return {
            "invitation_url": invitation["invitation_url"],
            "connection_id": connections["results"][0]["connection_id"],
        }

    def is_up(self):
        r = requests.get(
            f"{self.agent_url}/status",
            headers=self.headers,
        )
        if r.status_code != 200:
            return False
        return True

    def create_connectionless_request(self):
        r = requests.post(
            f"{self.agent_url}/present-proof-v2/create-request",
            headers=self.headers,
            json=RequestPresentation(
                proof_request=AnonCredsPresReq(
                    anoncreds=ProofRequest(
                        name="PerfScore",
                        requested_attributes={
                            item["name"]: {"name": item["name"]}
                            for item in self.cred_attributes
                        },
                        requested_predicates={},
                        version="1.0",
                    )
                ),
            ).model_dump(),
        )
        if r.status_code != 200:
            raise Exception("Request was not successful: ", r.content)
        try:
            return r.json()
        except JSONDecodeError:
            raise Exception(
                "Encountered JSONDecodeError while parsing the request: ", r.text
            )


    def request_verification(self, connection_id):
        r = requests.post(
            f"{self.agent_url}/present-proof-v2/create-request",
            headers=self.headers,
            json=RequestPresentation(
                connection_id=connection_id,
                proof_request=AnonCredsPresReq(
                    anoncreds=ProofRequest(
                        name="PerfScore",
                        requested_attributes={
                            item["name"]: {"name": item["name"]}
                            for item in self.cred_attributes
                        },
                        requested_predicates={},
                        version="1.0",
                    )
                ),
            ).model_dump(),
        )
        if r.status_code != 200:
            raise Exception("Request was not successful: ", r.content)

        try:
            return r.json()["presentation_exchange_id"]
        except JSONDecodeError:
            raise Exception(
                "Encountered JSONDecodeError while parsing the request: ", r.text
            )

    def verify_verification(self, pres_ex_id):
        # Want to do a for loop
        try:
            for iteration in range(self.verifiedTimeoutSeconds):
                r = requests.get(
                    f"{self.agent_url}/present-proof-v2/records/{pres_ex_id}",
                    headers=self.headers,
                )
                if (
                    r.json()["state"] != "request_sent"
                    and r.json()["state"] != "presentation_received"
                ):
                    "request_sent" and r.json()["state"] != "presentation_received"
                    break
                time.sleep(1)

            if r.json()["verified"] != "true":
                raise AssertionError(
                    f"Presentation was not successfully verified. Presentation in state {r.json()['state']}"
                )
                
            return True

        except JSONDecodeError as e:
            raise Exception(
                "Encountered JSONDecodeError while getting the presentation record: ", e
            )


    def send_message(self, connection_id, msg):
        r = requests.post(
            f"{self.agent_url}/connections/{connection_id}/send-message",
            headers=self.headers,
            json={"content": msg},
        )
        if r.status_code != 200:
            raise Exception(r.content)
