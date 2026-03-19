#!/usr/bin/env python3
"""
Test script for user login system
"""
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from services.user_manager import UserManager

def test_user_manager():
    """Test UserManager functionality"""
    print("=" * 60)
    print("Testing User Login System")
    print("=" * 60)

    # Initialize UserManager (will create users.json with default admin user)
    print("\n1. Initializing UserManager...")
    um = UserManager()
    print("   ✓ UserManager initialized")
    print(f"   ✓ users.json created at: {um.users_file}")

    # Test default admin login
    print("\n2. Testing default admin login (admin/admin)...")
    result = um.authenticate('admin', 'admin')
    print(f"   {'✓' if result else '✗'} Authentication result: {result}")

    # Test wrong password
    print("\n3. Testing wrong password (admin/wrongpass)...")
    result = um.authenticate('admin', 'wrongpass')
    print(f"   {'✓' if not result else '✗'} Authentication result: {result} (should be False)")

    # Test adding new user
    print("\n4. Testing adding new user (testuser/testpass)...")
    result = um.add_user('testuser', 'testpass')
    print(f"   {'✓' if result else '✗'} Add user result: {result}")

    # Test new user login
    print("\n5. Testing new user login (testuser/testpass)...")
    result = um.authenticate('testuser', 'testpass')
    print(f"   {'✓' if result else '✗'} Authentication result: {result}")

    # Test duplicate user
    print("\n6. Testing duplicate user (testuser)...")
    result = um.add_user('testuser', 'anotherpass')
    print(f"   {'✓' if not result else '✗'} Add user result: {result} (should be False)")

    # Test password change
    print("\n7. Testing password change (testuser: testpass -> newpass)...")
    result = um.change_password('testuser', 'testpass', 'newpass')
    print(f"   {'✓' if result else '✗'} Change password result: {result}")

    # Test login with new password
    print("\n8. Testing login with new password (testuser/newpass)...")
    result = um.authenticate('testuser', 'newpass')
    print(f"   {'✓' if result else '✗'} Authentication result: {result}")

    # Test login with old password (should fail)
    print("\n9. Testing login with old password (testuser/testpass)...")
    result = um.authenticate('testuser', 'testpass')
    print(f"   {'✓' if not result else '✗'} Authentication result: {result} (should be False)")

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
    print("\nDefault admin credentials:")
    print("  Username: admin")
    print("  Password: admin")
    print("\nYou can now start the web application with: python run_web.py")
    print("=" * 60)

if __name__ == '__main__':
    test_user_manager()
