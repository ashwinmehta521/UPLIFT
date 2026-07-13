"""
refresh_token.py
-----------------
Semi-automated daily Kite Connect session refresh.

Automates: navigating to login, entering user ID + password.
Pauses for: manual entry of the 6-digit TOTP code from your phone.
Automates: capturing the request_token from the redirect and exchanging
           it for an access_token, which is saved to .kite_session.

Run this once each morning before market open (or trigger manually via cron
with a notification, since it needs your TOTP input).

Requires .env with:
    KITE_API_KEY=xxxx
    KITE_API_SECRET=xxxx
    KITE_USER_ID=xxxx
    KITE_PASSWORD=xxxx

Deliberately does NOT store the TOTP secret. You type the code by hand.
"""

import os
import sys
import time

from dotenv import load_dotenv
from kiteconnect import KiteConnect
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")
USER_ID = os.getenv("KITE_USER_ID")
PASSWORD = os.getenv("KITE_PASSWORD")

SESSION_FILE = ".kite_session"


def fail(msg):
    print(f"[refresh_token] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if not all([API_KEY, API_SECRET, USER_ID, PASSWORD]):
        fail("Missing one or more required .env values "
             "(KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID, KITE_PASSWORD).")

    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()

    options = webdriver.ChromeOptions()
    # Keep the window visible since you need to see it to type the TOTP.
    driver = webdriver.Chrome(options=options)

    try:
        driver.get(login_url)
        wait = WebDriverWait(driver, 20)

        # --- Step 1: user ID + password ---
        userid_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        userid_field.send_keys(USER_ID)

        password_field = driver.find_element(By.ID, "password")
        password_field.send_keys(PASSWORD)

        submit_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
        submit_btn.click()

        # --- Step 2: manual TOTP entry ---
        print("\n" + "=" * 50)
        print("Enter your 6-digit TOTP code in the browser window now.")
        print("Waiting for you to complete login and be redirected...")
        print("=" * 50 + "\n")

        # Poll the URL until it contains request_token, or time out.
        timeout_seconds = 90
        start = time.time()
        request_token = None

        while time.time() - start < timeout_seconds:
            current_url = driver.current_url
            if "request_token=" in current_url:
                request_token = current_url.split("request_token=")[1].split("&")[0]
                break
            time.sleep(1)

        if not request_token:
            fail(f"Timed out after {timeout_seconds}s waiting for TOTP entry / redirect. "
                 "Re-run the script.")

        print(f"[refresh_token] Captured request_token: {request_token[:8]}...")

        # --- Step 3: exchange for access_token ---
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]

        with open(SESSION_FILE, "w") as f:
            f.write(access_token)
        os.chmod(SESSION_FILE, 0o600)

        print(f"[refresh_token] Success. Session saved to {SESSION_FILE}")
        print(f"[refresh_token] Access token: {access_token[:10]}...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()