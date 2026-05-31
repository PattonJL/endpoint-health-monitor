# Setup and Deployment Guide

## Prerequisites

- Windows 10, Windows 11, or Windows Server
- Python 3.8 or higher
- PowerShell (run as Administrator)
- psutil: `pip install psutil`
- Gmail account with 2-Step Verification and an App Password

---

## Step 1 — Install Dependencies

```powershell
pip install psutil
```

Verify:
```powershell
python -c "import psutil; print(psutil.__version__)"
```

---

## Step 2 — Set Email Credentials

If you already have the Windows Security Log Analyzer deployed,
your credentials are already set — skip this step.

Otherwise, open an Administrator PowerShell and run:

```powershell
[System.Environment]::SetEnvironmentVariable("ALERT_EMAIL_SENDER", "your@gmail.com", "User")
[System.Environment]::SetEnvironmentVariable("ALERT_EMAIL_PASSWORD", "your-app-password", "User")
[System.Environment]::SetEnvironmentVariable("ALERT_EMAIL_RECEIVER", "recipient@gmail.com", "User")
```

Restart PowerShell after setting these.

---

## Step 3 — Test the Script

```powershell
# Basic run — no email
python healthmonitor.py

# Full run with email alert if issues found
python healthmonitor.py --email

# Custom thresholds
python healthmonitor.py --threshold 80 --ram-threshold 80 --email
```

---

## Step 4 — Schedule with Task Scheduler

1. Open Task Scheduler → **Create Task**
2. **General tab**
   - Name: `Endpoint-HealthMonitor-Daily`
   - Check **Run with highest privileges**
3. **Triggers tab** — add two triggers:
   - Daily → 8:00 AM
   - Daily → 3:00 PM
4. **Actions tab**
   - Program: `python`
   - Arguments: `"C:\Scripts\endpoint-health-monitor\healthmonitor.py" --email`
   - Start in: `C:\Scripts\endpoint-health-monitor`
5. Click OK

---

## CLI Reference

```powershell
python healthmonitor.py [--threshold N] [--ram-threshold N] [--update-days N] [--email]
```

| Flag | Default | Description |
|---|---|---|
| `--threshold N` | `85` | Disk usage % to flag as critical |
| `--ram-threshold N` | `85` | RAM usage % to flag |
| `--update-days N` | `30` | Days since last update before flagging |
| `--email` | off | Send alert if any issues detected |

Email only sends when something is flagged. Clean runs stay silent.