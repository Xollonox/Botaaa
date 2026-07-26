"""Shared Firebase Admin SDK / Firestore client initialization."""

from __future__ import annotations

import json

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Client

_app: firebase_admin.App | None = None
_client: Client | None = None


def get_firestore_client(
    project_id: str,
    credentials_path: str | None = None,
    credentials_json: str | None = None,
) -> Client:
    """Return a process-wide Firestore client, initializing the Admin SDK once.

    Accepts credentials either as a file path or as the raw service account
    key JSON content (e.g. pasted into an env var on hosts without file
    upload access). If both are set, ``credentials_json`` wins.
    """
    global _app, _client
    if _client is not None:
        return _client

    if credentials_json:
        cred = credentials.Certificate(json.loads(credentials_json))
    elif credentials_path:
        cred = credentials.Certificate(credentials_path)
    else:
        raise ValueError("Either credentials_json or credentials_path must be provided.")

    _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
    _client = firestore.client(_app)
    return _client
