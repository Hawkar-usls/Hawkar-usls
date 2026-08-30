from __future__ import annotations

import json
import urllib.error

from janus_spi.activator import canonical_hash
from janus_spi.oidc_mailbox import (
    HOME_REPOSITORY, HOME_REPOSITORY_ID, HOME_WORKFLOW_REFS, IDENTITY_SCHEMA, ISSUER,
    OWNER, OWNER_ID, PROVENANCE_CLASS, TARGET_REPOSITORY, TARGET_REPOSITORY_ID,
    TARGET_WORKFLOW_REFS, JanusOIDCMailboxReader, JanusOIDCMailboxTransport,
    build_request_envelope, request_audience, response_audience,
    verify_request_envelope, verify_signed_response,
)


class Response:
    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
    def read(self): return self._body


def packet():
    row = {
        "schema":"janus.activator.dispatch_packet.v0.3","created_at":10.0,"activation_id":"act-test",
        "activation_receipt_hash":"a"*64,"route_match":"research_or_anomaly_investigation",
        "target_organ":TARGET_REPOSITORY,"operation":"WAKE_ORGAN_READ_ONLY",
        "risk_class":"R0_INTERNAL_READ_ONLY_ORGAN_WAKE","required_gates":[],"dispatch_authorized":True,
        "external_effect_authorized":False,"claim_authority_granted":False,"command_authority_granted":False,
        "effect_scope":"GITHUB_INTERNAL_READ_ONLY_ANALYSIS","delivery_terminal":"AUTHORIZED_INTERNAL_HANDOFF"
    }
    row["packet_id"]="dsp-"+canonical_hash({"activation_receipt_hash":row["activation_receipt_hash"],"target_organ":row["target_organ"],"operation":row["operation"]})
    row["packet_hash"]=canonical_hash(row)
    return row


def claims(target, audience, repo_id=None):
    return {
        "iss":ISSUER,"aud":audience,"iat":100,"nbf":100,"exp":700,
        "repository":TARGET_REPOSITORY if target else HOME_REPOSITORY,
        "repository_id":repo_id or (TARGET_REPOSITORY_ID if target else HOME_REPOSITORY_ID),
        "repository_owner":OWNER,"repository_owner_id":OWNER_ID,"ref":"refs/heads/main",
        "event_name":"schedule" if target else "push",
        "workflow_ref":next(iter(TARGET_WORKFLOW_REFS if target else HOME_WORKFLOW_REFS)),
        "workflow_sha":("2" if target else "1")*40,"run_id":"2" if target else "1","run_attempt":"1"
    }


def decoder(token,audience):
    if token.startswith("home."): return claims(False,audience)
    if token.startswith("target."): return claims(True,audience)
    raise ValueError("bad fake token")


def identity(role,audience,token,bound=150.0):
    return {"schema":IDENTITY_SCHEMA,"provider":"GITHUB_ACTIONS_OIDC","role":role,"audience":audience,"bound_at":bound,"jwt":token}


def request():
    p=packet(); aud=request_audience("DISPATCH_PACKET",p["packet_id"],p["packet_hash"])
    return build_request_envelope(p, identity("HOME_REQUEST_SOURCE",aud,"home.fake.jwt"))


def signed_response(req):
    ack={"schema":"janus.demiurge.activator_dispatch_ack.v0.1","created_at":155.0,"packet_id":req["object_id"],"packet_hash":req["object_hash"],"accepted":True,"terminal":"ACK_ACCEPTED_NO_EXECUTION","reasons":["test"],"execution_authorized":False,"execution_performed":False,"claim_authority_granted":False,"external_effect_authorized":False}
    ack["ack_hash"]=canonical_hash(ack)
    core={"schema":"janus.demiurge.mailbox_response_core.v1.1","created_at":155.0,"source_repository":TARGET_REPOSITORY,"target_repository":HOME_REPOSITORY,"target_head_sha":"9"*40,"request_message_hash":req["message_hash"],"request_object_kind":"DISPATCH_PACKET","request_object_id":req["object_id"],"request_object_hash":req["object_hash"],"response_kind":"DELIVERY_ACK","payload":{"ack":ack},"source_identity_verified":True,"source_identity_verification_hash":"f"*64,"source_identity_verification":{"ok":True},"target_execution_authorized":False,"target_execution_performed":False,"command_authority_granted":False,"claim_authority_granted":False,"scientific_evidence_authority_granted":False,"world_truth_authority_granted":False,"external_effect_authorized":False,"physical_runtime_effect_authorized":False,"terminal":"OIDC_MAILBOX_DELIVERY_ACK_CORE_READY"}
    ch=canonical_hash(core); aud=response_audience(req["message_hash"],ch)
    row={"schema":"janus.demiurge.mailbox_response.v1.1","response_core":core,"response_core_hash":ch,"target_identity":identity("DEMIURGE_RESPONSE_SOURCE",aud,"target.fake.jwt",160.0),"provenance_class":PROVENANCE_CLASS,"identity_proof":True}
    row["response_hash"]=canonical_hash(row)
    return row


def test_home_request_object_bound_and_explicit_authority_ceiling():
    req=request(); v=verify_request_envelope(req,decoder=decoder)
    assert v["ok"] is True and v["identity_proof"] is True
    assert req["world_truth_authority_granted"] is False


def test_wrong_home_repository_id_rejected():
    req=request()
    def wrong(token,aud): return claims(False,aud,repo_id="999")
    v=verify_request_envelope(req,decoder=wrong)
    assert v["ok"] is False and v["terminal"]=="OIDC_REPOSITORY_IDENTITY_REJECTED"


def test_target_signed_exact_response_verifies():
    req=request(); rsp=signed_response(req)
    v=verify_signed_response(rsp,request_envelope=req,decoder=decoder)
    assert v["ok"] is True and v["identity_proof"] is True


def test_legacy_or_unsigned_response_cannot_satisfy_oidc_reader():
    req=request(); legacy={"schema":"janus.demiurge.mailbox_response.v1.0","identity_proof":False}
    reader=JanusOIDCMailboxReader(opener=lambda r,timeout=15.0: Response(body=(json.dumps(legacy)+"\n").encode()),decoder=decoder)
    try: reader.read_verified(req)
    except ValueError as exc: assert "TARGET_RESPONSE_NOT_VERIFIED" in str(exc)
    else: raise AssertionError("legacy response accepted")


def test_existing_valid_request_is_reused_without_new_identity_issue(tmp_path):
    req=request(); calls=[]
    transport=JanusOIDCMailboxTransport(tmp_path,opener=lambda r,timeout=15.0: Response(body=(json.dumps(req)+"\n").encode()),decoder=decoder,identity_issuer=lambda aud: calls.append(aud) or identity("HOME_REQUEST_SOURCE",aud,"home.new.jwt"))
    result=transport.publish(req["object"],local_github_token="local")
    assert result["terminal"]=="OIDC_MAILBOX_ALREADY_PUBLISHED_VERIFIED"
    assert calls==[]
