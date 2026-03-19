"""
User authentication and management system
"""
import json
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict


class UserManager:
    """Manage user authentication"""

    def __init__(self, users_file: str = 'users.json'):
        """
        Initialize user manager

        Args:
            users_file: Path to users.json file
        """
        self.users_file = users_file
        self._ensure_users_file()

    def _ensure_users_file(self):
        """Ensure users.json exists"""
        if not os.path.exists(self.users_file):
            # Create default admin user (password: admin)
            default_users = {
                "admin": {
                    "password_hash": self.hash_password("admin"),
                    "created_at": datetime.now().isoformat(),
                    "last_login": None
                }
            }
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(default_users, f, indent=2, ensure_ascii=False)

    def hash_password(self, password: str) -> str:
        """
        Hash password using SHA-256 with salt

        Args:
            password: Plain text password

        Returns:
            Hashed password in format: salt$hash
        """
        # Generate random salt
        salt = secrets.token_hex(16)
        # Hash password with salt
        pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"{salt}${pwd_hash}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        """
        Verify password against stored hash

        Args:
            password: Plain text password to verify
            password_hash: Stored hash in format: salt$hash

        Returns:
            True if password matches
        """
        try:
            salt, stored_hash = password_hash.split('$')
            pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
            return pwd_hash == stored_hash
        except:
            return False

    def load_users(self) -> Dict:
        """Load users from file"""
        with open(self.users_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_users(self, users: Dict):
        """Save users to file"""
        with open(self.users_file, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2, ensure_ascii=False)

    def authenticate(self, username: str, password: str) -> bool:
        """
        Authenticate user

        Args:
            username: Username
            password: Plain text password

        Returns:
            True if authentication successful
        """
        users = self.load_users()

        if username not in users:
            return False

        user = users[username]
        if self.verify_password(password, user['password_hash']):
            # Update last login time
            user['last_login'] = datetime.now().isoformat()
            self.save_users(users)
            return True

        return False

    def add_user(self, username: str, password: str) -> bool:
        """
        Add new user

        Args:
            username: Username
            password: Plain text password

        Returns:
            True if user added successfully
        """
        users = self.load_users()

        if username in users:
            return False

        users[username] = {
            "password_hash": self.hash_password(password),
            "created_at": datetime.now().isoformat(),
            "last_login": None
        }

        self.save_users(users)
        return True

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Change user password

        Args:
            username: Username
            old_password: Current password
            new_password: New password

        Returns:
            True if password changed successfully
        """
        if not self.authenticate(username, old_password):
            return False

        users = self.load_users()
        users[username]['password_hash'] = self.hash_password(new_password)
        self.save_users(users)
        return True

    def user_exists(self, username: str) -> bool:
        """Check if user exists"""
        users = self.load_users()
        return username in users
