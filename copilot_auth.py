#!/usr/bin/env python3
"""
GitHub Copilot Web Authentication using Device Flow
"""

import json
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs
import requests


class CopilotAuth:
    """Handles GitHub Copilot authentication via device flow"""
    
    # GitHub Copilot OAuth App Client ID
    CLIENT_ID = 'Iv1.b507a08c87ecfe98'
    
    # Token storage
    TOKEN_DIR = Path.home() / '.copilot_chat'
    TOKEN_FILE = TOKEN_DIR / 'token.json'
    
    def __init__(self):
        self.TOKEN_DIR.mkdir(exist_ok=True)
        self.github_token = None
        self.copilot_token = None
    
    def load_token(self):
        """Load saved token from disk"""
        if self.TOKEN_FILE.exists():
            try:
                with open(self.TOKEN_FILE, 'r') as f:
                    data = json.load(f)
                    self.github_token = data.get('github_token')
                    self.copilot_token = data.get('copilot_token')
                    return True
            except Exception as e:
                print(f"Error loading token: {e}")
        return False
    
    def save_token(self):
        """Save token to disk"""
        try:
            with open(self.TOKEN_FILE, 'w') as f:
                json.dump({
                    'github_token': self.github_token,
                    'copilot_token': self.copilot_token
                }, f)
        except Exception as e:
            print(f"Error saving token: {e}")
    
    def authenticate(self):
        """Perform device flow authentication"""
        print("\n🔐 GitHub Copilot Web Authentication")
        print("=" * 60)
        
        # Step 1: Request device code
        print("\n📝 Step 1: Requesting device code...")
        url = 'https://github.com/login/device/code'
        response = requests.post(url, data={
            'client_id': self.CLIENT_ID,
            'scope': 'read:user'
        })
        
        if response.status_code != 200:
            print(f"❌ Failed to get device code: {response.status_code}")
            return False
        
        params = parse_qs(response.text)
        user_code = params['user_code'][0]
        verification_uri = params['verification_uri'][0]
        device_code = params['device_code'][0]
        
        # Display code to user
        print(f"\n✅ Device code received!")
        print(f"\n📋 Your one-time code: \033[93m{user_code}\033[0m")
        print(f"🌐 Verification URL: {verification_uri}")
        print(f"\n👉 Copy the code above and press Enter to open browser...")
        
        input()
        webbrowser.open(verification_uri)
        
        # Step 2: Poll for authorization
        print("\n⏳ Waiting for you to authorize in browser", end='', flush=True)
        interval = int(params['interval'][0]) + 1
        
        max_attempts = 60  # 5 minutes max
        attempts = 0
        
        while attempts < max_attempts:
            time.sleep(interval)
            print('.', end='', flush=True)
            attempts += 1
            
            poll_response = requests.post(
                'https://github.com/login/oauth/access_token',
                data={
                    'client_id': self.CLIENT_ID,
                    'device_code': device_code,
                    'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
                }
            )
            
            poll_params = parse_qs(poll_response.text)
            
            if 'error' in poll_params:
                error = poll_params['error'][0]
                if error == 'authorization_pending':
                    continue
                elif error == 'slow_down':
                    interval += 5
                    continue
                else:
                    print(f"\n❌ Error: {error}")
                    return False
            
            if 'access_token' in poll_params:
                self.github_token = poll_params['access_token'][0]
                print("\n\n✅ GitHub token received!")
                break
        
        if not self.github_token:
            print("\n❌ Timeout waiting for authorization")
            return False
        
        # Step 3: Exchange for Copilot token
        print("🔄 Exchanging for Copilot token...")
        if self.get_copilot_token():
            self.save_token()
            print("✅ Authentication complete!\n")
            return True
        else:
            print("⚠️  Using GitHub token directly\n")
            self.save_token()
            return True
    
    def get_copilot_token(self):
        """Exchange GitHub token for Copilot-specific token"""
        headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/json',
            'Editor-Version': 'vscode/1.85.1',
            'Editor-Plugin-Version': 'copilot/1.155.0',
            'User-Agent': 'GithubCopilot/1.155.0'
        }
        
        try:
            response = requests.get(
                'https://api.github.com/copilot_internal/v2/token',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.copilot_token = data.get('token')
                print("✅ Copilot token obtained!")
                return True
            else:
                print(f"⚠️  Could not get Copilot token (status {response.status_code})")
                return False
        except Exception as e:
            print(f"⚠️  Error getting Copilot token: {e}")
            return False
    
    def get_headers(self):
        """Get headers for Copilot API requests"""
        token = self.copilot_token or self.github_token
        
        # If no token loaded, try loading from disk
        if not token:
            self.load_token()
            token = self.copilot_token or self.github_token
        
        if not token:
            raise ValueError("No authentication token available. Please run authenticate() first.")
        
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Editor-Version': 'vscode/1.85.1',
            'Editor-Plugin-Version': 'copilot/1.155.0',
            'Copilot-Integration-Id': 'vscode-chat',
            'User-Agent': 'GithubCopilot/1.155.0',
            'Accept': 'application/json'
        }
