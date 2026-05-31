import psutil
import subprocess
import smtplib
import argparse
import os
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# Reuses the same environment variables as the login analyzer
# No new credential setup required
# ─────────────────────────────────────────────

SENDER_EMAIL   = os.environ.get("ALERT_EMAIL_SENDER")
SENDER_PASS    = os.environ.get("ALERT_EMAIL_PASSWORD")
RECEIVER_EMAIL = os.environ.get("ALERT_EMAIL_RECEIVER")

# Services to verify are running on every check
WATCHED_SERVICES = [
    ("WinDefend", "Windows Defender"),
    ("wuauserv",  "Windows Update"),
    ("MpsSvc",    "Windows Firewall"),
    ("EventLog",  "Windows Event Log"),
    ("Schedule",  "Task Scheduler"),
]


# ─────────────────────────────────────────────
# COMMAND-LINE ARGUMENTS
# Examples:
#   python health_monitor.py
#   python health_monitor.py --quick --email
#   python health_monitor.py --threshold 90 --update-days 14 --email
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Windows Endpoint Health Monitor")
    parser.add_argument('--threshold', type=int, default=85,
                        help='Disk usage %% to flag as critical (default: 85)')
    parser.add_argument('--update-days', type=int, default=30,
                        help='Flag if last Windows Update was more than N days ago (default: 30)')
    parser.add_argument('--email', action='store_true',
                        help='Send email alert if any issues are detected')
    parser.add_argument('--ram-threshold', type=int, default=85,
                    help='RAM usage %% to flag in quick mode (default: 85)')
    return parser.parse_args()


# ─────────────────────────────────────────────
# DISK USAGE
# ─────────────────────────────────────────────

def check_disks(threshold):
    results = []
    flagged = False
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            pct = usage.percent
            if pct >= threshold:
                flagged = True
            results.append({
                'drive'  : part.device,
                'total'  : usage.total,
                'used'   : usage.used,
                'free'   : usage.free,
                'percent': pct,
                'flagged': pct >= threshold,
            })
        except PermissionError:
            continue
    return results, flagged


# ─────────────────────────────────────────────
# SYSTEM UPTIME
# ─────────────────────────────────────────────

def check_uptime():
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    delta = datetime.now() - boot_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes = remainder // 60
    return boot_time, days, hours, minutes


# ─────────────────────────────────────────────
# WINDOWS UPDATE — last installed hotfix date
# ─────────────────────────────────────────────

def check_last_update(max_days):
    ps_command = """
    try {
        $hotfix = Get-HotFix | Sort-Object InstalledOn -Descending |
                  Select-Object -First 1
        if ($hotfix -and $hotfix.InstalledOn) {
            $hotfix.InstalledOn.ToString('yyyy-MM-dd')
        } else {
            'unknown'
        }
    } catch {
        'error'
    }
    """
    result = subprocess.run(
        ['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_command],
        capture_output=True, text=True
    )
    date_str = result.stdout.strip()

    if date_str in ('unknown', 'error', ''):
        return 'Unknown', -1, False

    try:
        last_update = datetime.strptime(date_str, '%Y-%m-%d')
        days_ago    = (datetime.now() - last_update).days
        flagged     = days_ago > max_days
        return date_str, days_ago, flagged
    except Exception:
        return date_str, -1, False


# ─────────────────────────────────────────────
# CRITICAL SERVICES
# ─────────────────────────────────────────────

def check_services():
    results = []
    flagged = False
    for svc_name, display_name in WATCHED_SERVICES:
        try:
            svc    = psutil.win_service_get(svc_name)
            status = svc.status()
            ok     = status == 'running'
        except Exception:
            status = 'not found'
            ok     = False
        if not ok:
            flagged = True
        results.append({
            'name'  : display_name,
            'status': status,
            'ok'    : ok,
            'icon'  : '✅' if ok else '🚨',
        })
    return results, flagged


# ─────────────────────────────────────────────
# LIVE RAM + CPU SNAPSHOT (only with --quick)
# ─────────────────────────────────────────────

def check_live_stats():
    cpu = psutil.cpu_percent(interval=2)
    ram = psutil.virtual_memory()
    return cpu, ram.percent, ram.total, ram.used, ram.available


# ─────────────────────────────────────────────
# HELPER — bytes to GB
# ─────────────────────────────────────────────

def to_gb(b):
    return round(b / (1024 ** 3), 1)


# ─────────────────────────────────────────────
# BUILD REPORT
# ─────────────────────────────────────────────

def build_report(args, machine, disks, disk_flagged, boot_time,
                 up_days, up_hrs, up_mins, services, svc_flagged,
                 last_update, days_since_update, update_flagged,
                 cpu_pct=None, ram_pct=None,
                 ram_total=None, ram_used=None, ram_avail=None, 
                 ram_threshold=85):

    now         = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ram_flagged = (ram_pct is not None) and (ram_pct >= ram_threshold)
    any_flagged = disk_flagged or svc_flagged or update_flagged or ram_flagged
    lines       = []

    lines.append("=" * 60)
    lines.append("       ENDPOINT HEALTH MONITOR REPORT")
    lines.append(f"       Generated : {now}")
    lines.append(f"       Machine   : {machine}")
    lines.append("=" * 60)

    status_line = "⚠️  ISSUES DETECTED" if any_flagged else "✅  ALL CHECKS PASSED"
    lines.append(f"\n  {status_line}\n")

    # ── Disk ──────────────────────────────────
    lines.append("─" * 60)
    lines.append("  DISK USAGE")
    lines.append("─" * 60)
    for d in disks:
        filled = int(d['percent'] / 2.5)
        bar    = '█' * filled + '░' * (40 - filled)
        flag   = "  ⚠️  CRITICAL" if d['flagged'] else "  ✅ OK"
        lines.append(f"  {d['drive']:<6}  {d['percent']:>5.1f}%  {bar}{flag}")
        lines.append(f"          Used {to_gb(d['used'])} GB of {to_gb(d['total'])} GB"
                     f"  |  Free: {to_gb(d['free'])} GB")

    # ── Uptime ────────────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("  SYSTEM UPTIME")
    lines.append("─" * 60)
    lines.append(f"  Last reboot : {boot_time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Uptime      : {up_days}d  {up_hrs}h  {up_mins}m")

    # ── Windows Update ────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("  WINDOWS UPDATE")
    lines.append("─" * 60)
    if days_since_update >= 0:
        icon = "⚠️ " if update_flagged else "✅"
        lines.append(f"  {icon} Last update : {last_update}  ({days_since_update} days ago)")
        if update_flagged:
            lines.append(f"       Exceeds {args.update_days}-day threshold — check for pending updates")
    else:
        lines.append(f"  Last update : {last_update}")

    # ── Services ──────────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("  CRITICAL SERVICES")
    lines.append("─" * 60)
    for svc in services:
        lines.append(f"  {svc['icon']}  {svc['name']:<30}  {svc['status'].upper()}")

    # ── Live snapshot (--quick only) ──────────
    if cpu_pct is not None:
        lines.append("\n" + "─" * 60)
        lines.append("  LIVE SNAPSHOT  (point-in-time)")
        lines.append("─" * 60)
        lines.append(f"  CPU   : {cpu_pct:.1f}%")
        ram_icon   = "⚠️ " if ram_flagged else "✅"
        ram_status = "  HIGH" if ram_flagged else "  OK"
        lines.append(f"  RAM   : {ram_icon} {ram_pct:.1f}%  "
                     f"({to_gb(ram_used)} GB used / {to_gb(ram_total)} GB total  |  "
                     f"{to_gb(ram_avail)} GB free){ram_status}")
        if ram_flagged:
            lines.append(f"       Exceeds {ram_threshold}% threshold — check for memory-heavy processes")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines), any_flagged


# ─────────────────────────────────────────────
# EMAIL ALERT
# Only fires when --email is passed AND issues are found
# ─────────────────────────────────────────────

def send_alert(report_text, machine):
    if not all([SENDER_EMAIL, SENDER_PASS, RECEIVER_EMAIL]):
        print("  ⚠️  Email credentials missing from environment variables.\n")
        return

    now            = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg            = MIMEMultipart('alternative')
    msg['Subject'] = f"⚠️ HEALTH ALERT — Issues detected on {machine} | {now}"
    msg['From']    = SENDER_EMAIL
    msg['To']      = RECEIVER_EMAIL
    msg.attach(MIMEText(f"Endpoint health issues detected on {machine}.\n\n{report_text}", 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print("  📧 Alert email sent successfully.\n")
    except Exception as e:
        print(f"  ❌ Email failed: {e}\n")


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    args    = parse_args()
    machine = os.environ.get('COMPUTERNAME', socket.gethostname())

    print(f"\n🔍 Running health check on {machine}...\n")

    disks,    disk_flagged   = check_disks(args.threshold)
    boot_time, up_days, up_hrs, up_mins = check_uptime()
    services, svc_flagged    = check_services()
    last_update, days_since_update, update_flagged = check_last_update(args.update_days)

    print("  📊 Sampling CPU usage (2 seconds)...\n")
    cpu_pct, ram_pct, ram_total, ram_used, ram_avail = check_live_stats()

    report, any_flagged = build_report(
        args, machine, disks, disk_flagged,
        boot_time, up_days, up_hrs, up_mins,
        services, svc_flagged,
        last_update, days_since_update, update_flagged,
        cpu_pct, ram_pct, ram_total, ram_used, ram_avail,
        ram_threshold=args.ram_threshold
    )

    print(report)

    filename = f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n  📄 Report saved to: {filename}\n")

    if args.email:
        if any_flagged:
            send_alert(report, machine)
        else:
            print("  📧 All checks passed — no alert sent.\n")