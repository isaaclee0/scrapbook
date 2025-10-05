"""
Authentication utilities for JWT token generation and validation
"""

import jwt
import os
from datetime import datetime, timedelta
from typing import Optional, Dict

# Load configuration from environment
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-this')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
MAGIC_LINK_EXPIRY = int(os.getenv('MAGIC_LINK_EXPIRY', 1800))  # 30 minutes default
SESSION_EXPIRY = int(os.getenv('SESSION_EXPIRY', 2592000))  # 30 days default


def generate_magic_link_token(email: str) -> str:
    """
    Generate a short-lived JWT token for magic link authentication
    
    Args:
        email: User's email address
        
    Returns:
        JWT token string
    """
    payload = {
        'email': email,
        'type': 'magic_link',
        'exp': datetime.utcnow() + timedelta(seconds=MAGIC_LINK_EXPIRY),
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def generate_session_token(user_id: int, email: str) -> str:
    """
    Generate a long-lived JWT token for session management
    
    Args:
        user_id: User's database ID
        email: User's email address
        
    Returns:
        JWT token string
    """
    payload = {
        'user_id': user_id,
        'email': email,
        'type': 'session',
        'exp': datetime.utcnow() + timedelta(seconds=SESSION_EXPIRY),
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def verify_token(token: str, token_type: str = None) -> Optional[Dict]:
    """
    Verify and decode a JWT token
    
    Args:
        token: JWT token string to verify
        token_type: Expected token type ('magic_link' or 'session'), optional
        
    Returns:
        Decoded payload dict if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Validate token type if specified
        if token_type and payload.get('type') != token_type:
            return None
            
        return payload
        
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None


def is_token_expired(token: str) -> bool:
    """
    Check if a token is expired without raising an exception
    
    Args:
        token: JWT token string
        
    Returns:
        True if expired, False if still valid
    """
    try:
        jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return False
    except jwt.ExpiredSignatureError:
        return True
    except jwt.InvalidTokenError:
        return True


def refresh_session_token(old_token: str) -> Optional[str]:
    """
    Refresh a session token if it's close to expiring
    
    Args:
        old_token: Existing session token
        
    Returns:
        New token if successfully refreshed, None if invalid
    """
    payload = verify_token(old_token, token_type='session')
    
    if not payload:
        return None
    
    # Check if token is within 7 days of expiring
    exp_timestamp = payload.get('exp')
    if exp_timestamp:
        exp_date = datetime.fromtimestamp(exp_timestamp)
        days_until_expiry = (exp_date - datetime.utcnow()).days
        
        # Refresh if less than 7 days until expiry
        if days_until_expiry < 7:
            return generate_session_token(payload['user_id'], payload['email'])
    
    return old_token  # Return old token if not time to refresh yet
