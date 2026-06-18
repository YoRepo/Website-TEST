# path: wsgi.py
"""WSGI entry point for production (gunicorn on Render).
Start command: gunicorn wsgi:app
"""
from app import create_app

app = create_app()