"""Shared Firebase Admin SDK / Firestore client initialization."""

from __future__ import annotations

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Client

_app: firebase_admin.App | None = None
_client: Client | None = None


def get_firestore_client(project_id: str, credentials_path: str) -> Client:
    """Return a process-wide Firestore client, initializing the Admin SDK once."""
    global _app, _client
    if _client is not None:
        return _client

    cred = credentials.Certificate(credentials_path)
    _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
    _client = firestore.client(_app)
    return _client
