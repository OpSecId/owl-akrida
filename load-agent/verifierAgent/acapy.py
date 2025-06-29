from .base import BaseVerifier
import json
import os
import requests
import time

from json.decoder import JSONDecodeError

VERIFIED_TIMEOUT_SECONDS = int(os.getenv("VERIFIED_TIMEOUT_SECONDS", 20))

class AcapyVerifier(BaseVerifier):

        def get_invite(self):
                headers = json.loads(os.getenv("VERIFIER_HEADERS"))
                headers["Content-Type"] = "application/json"

                # Out of Band Connection 
                r = requests.post(
                        os.getenv("VERIFIER_URL") + "/out-of-band/create-invitation?auto_accept=true", 
                        json={
                        "metadata": {}, 
                        "handshake_protocols": ["did:sov:BzCbsNYhMrjHiqZDTUASHg;spec/didexchange/1.0"]
                        },
                        headers=headers
                )

                r = r.json()

                invitation_msg_id = r['invi_msg_id']
                g = requests.get(
                        os.getenv("VERIFIER_URL") + "/connections",
                        params={"invitation_msg_id": invitation_msg_id},
                        headers=headers,
                )
                # Returns only one
                connection_id = g.json()['results'][0]['connection_id']
                r['connection_id'] = connection_id 
                
                return {
                        'invitation_url': r['invitation_url'], 
                        'connection_id': r['connection_id']
                }

        def is_up(self):
                try:
                        headers = json.loads(os.getenv("VERIFIER_HEADERS"))
                        headers["Content-Type"] = "application/json"
                        r = requests.get(
                                os.getenv("VERIFIER_URL") + "/status",
                                json={"metadata": {}, "my_label": "Test"},
                                headers=headers,
                        )
                        if r.status_code != 200:
                                raise Exception(r.content)

                        r = r.json()
                except:
                        return False

                return True

        def create_connectionless_request(self):
                # Calling verification agent
                headers = json.loads(os.getenv("VERIFIER_HEADERS"))
                headers["Content-Type"] = "application/json"

                # API call to /present-proof/create-request
                r = requests.post(
                        os.getenv("VERIFIER_URL") + "/present-proof/create-request",
                        json={
                                "auto_remove": False,
                                "auto_verify": True,
                                "comment": "Performance Verification",
                                "proof_request": {
                                "name": "PerfScore",
                                "requested_attributes": {
                                        item["name"]: {"name": item["name"]}
                                        for item in json.loads(os.getenv("CRED_ATTR"))
                                },
                                "requested_predicates": {},
                                "version": "1.0",
                                },
                                "trace": True,
                        },
                        headers=headers,
                )

                try:
                        if r.status_code != 200:
                                raise Exception("Request was not successful: ", r.content)
                except JSONDecodeError as e:
                        raise Exception(
                                "Encountered JSONDecodeError while parsing the request: ", r
                        )
                
                r = r.json()

                return r
        
        def request_verification(self, connection_id):
                # From verification side
                headers = json.loads(os.getenv("VERIFIER_HEADERS"))  # headers same
                headers["Content-Type"] = "application/json"

                verifier_did = os.getenv("CRED_DEF").split(":")[0]
                schema_parts = os.getenv("SCHEMA").split(":")

                # Might need to change nonce
                # TO DO: Generalize schema parts
                r = requests.post(
                        os.getenv("VERIFIER_URL") + "/present-proof/send-request",
                        json={
                                "auto_remove": False,
                                "auto_verify": True,
                                "comment": "Performance Verification",
                                "connection_id": connection_id,
                                "proof_request": {
                                "name": "PerfScore",
                                "requested_attributes": {
                                        item["name"]: {"name": item["name"]}
                                        for item in json.loads(os.getenv("CRED_ATTR"))
                                },
                                "requested_predicates": {},
                                "version": "1.0",
                                },
                                "trace": True,
                        },
                        headers=headers,
                )

                try:
                        if r.status_code != 200:
                                raise Exception("Request was not successful: ", r.content)
                except JSONDecodeError as e:
                        raise Exception(
                                "Encountered JSONDecodeError while parsing the request: ", r
                        )
                
                r = r.json()

                return r['presentation_exchange_id']

        def verify_verification(self, presentation_exchange_id):
                headers = json.loads(os.getenv("VERIFIER_HEADERS"))  # headers same
                headers["Content-Type"] = "application/json"
                
                # Want to do a for loop
                iteration = 0
                try:
                        while iteration < VERIFIED_TIMEOUT_SECONDS:
                                g = requests.get(
                                        os.getenv("VERIFIER_URL") + f"/present-proof/records/{presentation_exchange_id}",
                                        headers=headers,
                                )
                                if (
                                        g.json()["state"] != "request_sent"
                                        and g.json()["state"] != "presentation_received"
                                ):
                                        "request_sent" and g.json()["state"] != "presentation_received"
                                        break
                                iteration += 1
                                time.sleep(1)

                        if g.json()["verified"] != "true":
                                raise AssertionError(
                                        f"Presentation was not successfully verified. Presentation in state {g.json()['state']}"
                                )

                except JSONDecodeError as e:
                        raise Exception(
                                "Encountered JSONDecodeError while getting the presentation record: ", g
                        )

                return True

        def send_message(self, connection_id, msg):
                headers = json.loads(os.getenv("VERIFIER_HEADERS"))
                headers["Content-Type"] = "application/json"

                r = requests.post(
                        os.getenv("ISSUER_URL") + "/connections/" + connection_id + "/send-message",
                        json={"content": msg},
                        headers=headers,
                )
                r = r.json()
