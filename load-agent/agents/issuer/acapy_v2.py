from .base import BaseIssuer
import requests
import time
from models import (
    IssueCredentialV2 as IssueCredential, 
    CredentialPreview, 
    AnonCredsFilter, 
    Filter, 
    AnonCredsRevocation
)
from settings import Settings


class AcapyIssuer(BaseIssuer):
    def __init__(self):
        self.label = "Test Issuer"
        self.filter = Settings.FILTER_TYPE
        self.agent_url = Settings.ISSUER_URL
        self.headers = Settings.ISSUER_HEADERS | {"Content-Type": "application/json"}
        self.schema_id = Settings.SCHEMA_ID
        self.cred_def_id = Settings.CRED_DEF_ID
        self.cred_attributes = Settings.CRED_ATTR

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

    def issue_credential(self, connection_id):
        r = requests.post(
            f"{self.agent_url}/issue-credential-v2/send",
            headers=self.headers,
            json=IssueCredential(
                connection_id=connection_id,
                credential_preview=CredentialPreview(
                    attributes=self.cred_attributes
                ),
                filter=AnonCredsFilter(
                    anoncreds=Filter(
                        cred_def_id=self.cred_def_id
                        )
                )
            ).model_dump(),
        )
        if r.status_code != 200:
            raise Exception(r.content)
        
        cred_ex = r.json()

        return {
            "connection_id": cred_ex["connection_id"],
            "cred_ex_id": cred_ex["credential_exchange_id"],
        }

    def revoke_credential(self, connection_id, cred_ex_id):
        time.sleep(1)
        r = requests.post(
            f"{self.agent_url}/revocation/revoke",
            headers=self.headers,
            json=AnonCredsRevocation(
                connection_id=connection_id,
                cred_ex_id=cred_ex_id,
                notify_version="v1_0",
            ).model_dump(),
        )
        if r.status_code != 200:
            raise Exception(r.content)

    def send_message(self, connection_id, msg):
        r = requests.post(
            f"{self.agent_url}/connections/{connection_id}/send-message",
            headers=self.headers,
            json={"content": msg},
        )
        if r.status_code != 200:
            raise Exception(r.content)
