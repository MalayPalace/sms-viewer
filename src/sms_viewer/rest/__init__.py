"""
REST API and Authentication routes package for SMS Viewer.
"""

from sms_viewer.rest.api import api_bp
from sms_viewer.rest.auth import auth_bp, login_required

__all__ = ["api_bp", "auth_bp", "login_required"]
