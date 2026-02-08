"""
Notification Tool - Sends alerts and nudges to the user.
"""
import os
import subprocess


def run(message: str = "", title: str = "Ankita Alert", **kwargs) -> dict:
    """
    Send a system notification or terminal message.
    """
    if not message:
        return {"status": "fail", "reason": "No message provided"}

    try:
        # 1. Try Windows Toast Notification (via powershell)
        ps_script = f"""
        [void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');
        $objNotification = New-Object System.Windows.Forms.NotifyIcon;
        $objNotification.Icon = [System.Drawing.SystemIcons]::Information;
        $objNotification.BalloonTipIcon = 'Info';
        $objNotification.BalloonTipText = '{message}';
        $objNotification.BalloonTipTitle = '{title}';
        $objNotification.Visible = $True;
        $objNotification.ShowBalloonTip(10000);
        """
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
        
        # 2. Always print to terminal for visibility
        print(f"\n[ANIKTA NUDGE] {title}: {message}\n")
        
        return {"status": "success", "message": "Notification sent"}
    except Exception as e:
        # Fallback to simple print
        print(f"\n[ANKITA NUDGE] {message}\n")
        return {"status": "success", "message": "Notification printed to terminal (fallback)"}
