import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import click
import psutil
from rich import print
from rich.table import Table


def gb(n: int) -> float:
    return round(n / (1024**3), 2)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return (r.stdout or r.stderr or "").strip()


def run_root(cmd):
    r = subprocess.run(["sudo"] + cmd, capture_output=True, text=True, check=False)
    return (r.stdout or r.stderr or "").strip()

def run_ping(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)

@click.group(name="fedcare", help="Fedora maintenance & system monitoring tool")
def cli():
    pass


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def health(as_json):
    """Show system health summary."""
    cpu_percent = psutil.cpu_percent(interval=0.5)
    load1, load5, load15 = psutil.getloadavg()

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    du = shutil.disk_usage("/")

    boot = datetime.fromtimestamp(psutil.boot_time())
    uptime_sec = int((datetime.now() - boot).total_seconds())
    uptime_h = uptime_sec // 3600
    uptime_m = (uptime_sec % 3600) // 60

    systemd_analyze = run(["systemd-analyze"]) or "Could not read systemd-analyze"

    data = {
        "cpu_percent": cpu_percent,
        "load_avg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "ram": {"percent": vm.percent, "used_gb": gb(vm.used), "total_gb": gb(vm.total)},
        "swap": {"percent": swap.percent, "used_gb": gb(swap.used), "total_gb": gb(swap.total)},
        "disk_root": {"used_gb": gb(du.used), "total_gb": gb(du.total), "free_gb": gb(du.free)},
        "uptime": {"hours": uptime_h, "minutes": uptime_m},
        "boot_summary": systemd_analyze,
    }

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    t = Table(title="Fedora Care • Health", show_lines=True)
    t.add_column("Field", style="bold")
    t.add_column("Value")

    t.add_row("CPU Usage", f"{cpu_percent}%")
    t.add_row("Load Avg", f"{load1:.2f} / {load5:.2f} / {load15:.2f}")
    t.add_row("RAM", f"{vm.percent}%  ({gb(vm.used)} / {gb(vm.total)} GB)")
    t.add_row("SWAP", f"{swap.percent}% ({gb(swap.used)} / {gb(swap.total)} GB)")
    t.add_row("Disk /", f"{gb(du.used)} / {gb(du.total)} GB  (Free: {gb(du.free)} GB)")
    t.add_row("Uptime", f"{uptime_h}h {uptime_m}m")
    t.add_row("Boot Time", systemd_analyze)

    print(t)


@cli.command()
@click.option("--since", default="10m", show_default=True, help="Time range (e.g. 10m, 1h, 1d)")
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def logs(since, as_json):
    """Show recent error/warning counts."""
    err = run(["journalctl", "--since", since, "-p", "err", "--no-pager"])
    warn = run(["journalctl", "--since", since, "-p", "warning", "--no-pager"])

    err_count = len([l for l in (err.splitlines() if err else []) if l.strip()])
    warn_count = len([l for l in (warn.splitlines() if warn else []) if l.strip()])

    data = {"since": since, "errors": err_count, "warnings": warn_count}

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    t = Table(title=f"Logs • Last {since}", show_lines=True)
    t.add_column("Level", style="bold")
    t.add_column("Count")
    t.add_row("ERROR", str(err_count))
    t.add_row("WARNING", str(warn_count))
    print(t)

    if err_count == 0 and warn_count == 0:
        print("[bold green]All clear ✅[/bold green]")
    else:
        print("[bold yellow]For details:[/bold yellow]")
        print(f"  journalctl --since {since} -p err")
        print(f"  journalctl --since {since} -p warning")


@cli.command()
@click.option("--apply", is_flag=True, help="Actually apply (requires sudo).")
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def clean(apply, as_json):
    """Cache/log cleanup (default: dry-run)."""
    actions = [
        {"name": "DNF cache cleanup", "command": ["dnf", "clean", "all"]},
        {"name": "Trim old journal logs (1 week)", "command": ["journalctl", "--vacuum-time=7d"]},
    ]

    if as_json:
        payload = {
            "mode": "apply" if apply else "dry-run",
            "actions": [{"name": a["name"], "command": " ".join(a["command"])} for a in actions],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if apply:
            for a in actions:
                run_root(a["command"])
        return

    t = Table(title="Clean • Plan", show_lines=True)
    t.add_column("Action", style="bold")
    t.add_column("Command")
    t.add_column("Mode")

    for a in actions:
        t.add_row(a["name"], " ".join(a["command"]), "APPLY" if apply else "DRY-RUN")

    print(t)

    if not apply:
        print("\n[bold yellow]Dry-run:[/bold yellow] Nothing was deleted.")
        print("To apply: [bold]fedcare clean --apply[/bold]")
        return

    print("\n[bold]Applying (may require sudo)...[/bold]")
    for a in actions:
        print(f"\n[bold]{a['name']}[/bold]")
        out = run_root(a["command"])
        print(out if out else "OK")

    print("\n[bold green]Cleanup complete ✅[/bold green]")


@cli.command()
@click.option("--since", default="10m", show_default=True, help="Log time range")
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def report(since, as_json):
    """Show Health + Logs + Clean plan at once."""
    # --- health ---
    cpu_percent = psutil.cpu_percent(interval=0.5)
    load1, load5, load15 = psutil.getloadavg()
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    du = shutil.disk_usage("/")
    boot = datetime.fromtimestamp(psutil.boot_time())
    uptime_sec = int((datetime.now() - boot).total_seconds())
    uptime_h = uptime_sec // 3600
    uptime_m = (uptime_sec % 3600) // 60
    systemd_analyze = run(["systemd-analyze"]) or "?"

    # --- logs ---
    err = run(["journalctl", "--since", since, "-p", "err", "--no-pager"])
    warn = run(["journalctl", "--since", since, "-p", "warning", "--no-pager"])
    err_count = len([l for l in (err.splitlines() if err else []) if l.strip()])
    warn_count = len([l for l in (warn.splitlines() if warn else []) if l.strip()])

    # --- clean plan ---
    clean_actions = [
        {"name": "DNF cache cleanup", "command": "dnf clean all"},
        {"name": "Trim old journal logs (1 week)", "command": "journalctl --vacuum-time=7d"},
    ]

    if as_json:
        data = {
            "health": {
                "cpu_percent": cpu_percent,
                "load_avg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
                "ram": {"percent": vm.percent, "used_gb": gb(vm.used), "total_gb": gb(vm.total)},
                "swap": {"percent": swap.percent, "used_gb": gb(swap.used), "total_gb": gb(swap.total)},
                "disk_root": {"used_gb": gb(du.used), "total_gb": gb(du.total), "free_gb": gb(du.free)},
                "uptime": {"hours": uptime_h, "minutes": uptime_m},
                "boot_summary": systemd_analyze,
            },
            "logs": {"since": since, "errors": err_count, "warnings": warn_count},
            "clean": {"mode": "dry-run", "actions": clean_actions},
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    t = Table(title="Fedora Care • Full Report", show_lines=True)
    t.add_column("Category", style="bold")
    t.add_column("Field", style="bold")
    t.add_column("Value")

    t.add_row("Health", "CPU", f"{cpu_percent}%")
    t.add_row("Health", "Load Avg", f"{load1:.2f} / {load5:.2f} / {load15:.2f}")
    t.add_row("Health", "RAM", f"{vm.percent}%  ({gb(vm.used)} / {gb(vm.total)} GB)")
    t.add_row("Health", "SWAP", f"{swap.percent}% ({gb(swap.used)} / {gb(swap.total)} GB)")
    t.add_row("Health", "Disk /", f"{gb(du.used)} / {gb(du.total)} GB  (Free: {gb(du.free)} GB)")
    t.add_row("Health", "Uptime", f"{uptime_h}h {uptime_m}m")
    t.add_row("Health", "Boot", systemd_analyze)
    t.add_row("Logs", f"Errors (last {since})", str(err_count))
    t.add_row("Logs", f"Warnings (last {since})", str(warn_count))
    for a in clean_actions:
        t.add_row("Clean", a["name"], f"[dim]{a['command']}[/dim]  (dry-run)")

    print(t)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def services(as_json):
    """Show status of critical systemd services."""
    svc_list = ["NetworkManager", "firewalld", "sshd", "crond", "bluetooth"]
    results = []
    for svc in svc_list:
        status = run(["systemctl", "is-active", svc])
        if status not in ("active", "inactive"):
            status = "not-found"
        results.append({"name": svc, "status": status})

    if as_json:
        print(json.dumps({"services": results}, ensure_ascii=False, indent=2))
        return

    t = Table(title="Fedora Care • Services", show_lines=True)
    t.add_column("Service", style="bold")
    t.add_column("Status")
    for s in results:
        color = "green" if s["status"] == "active" else "red" if s["status"] == "inactive" else "dim"
        t.add_row(s["name"], f"[{color}]{s['status']}[/{color}]")
    print(t)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def network(as_json):
    """Show network info and connectivity test."""
    # Interfaces
    ifaces = {}
    for iface, addrs in psutil.net_if_addrs().items():
        ips = [a.address for a in addrs if a.family.name == "AF_INET"]
        if ips:
            ifaces[iface] = ips

    # DNS
    dns_servers = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                line = line.strip()
                if line.startswith("nameserver"):
                    dns_servers.append(line.split()[1])
    except FileNotFoundError:
        pass

    # Ping tests
    ping_ip = run(["ping", "-c1", "-W2", "8.8.8.8"])
    ping_dns = run(["ping", "-c1", "-W2", "google.com"])
    ping_ip_ok = run_ping(["ping", "-1", "-W1" "8.8.8.8"])
    ping_dns_ok = run_ping(["ping", "-c1", "-W2", "google.com"])
    data = {
        "interfaces": ifaces,
        "dns": dns_servers,
        "ping_ip": "OK" if ping_ip_ok else "FAIL",
        "ping_dns": "OK" if ping_dns_ok else "FAIL",
    }

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    t = Table(title="Fedora Care • Network", show_lines=True)
    t.add_column("Field", style="bold")
    t.add_column("Value")
    for iface, ips in ifaces.items():
        t.add_row(f"Interface: {iface}", ", ".join(ips))
    t.add_row("DNS", ", ".join(dns_servers) if dns_servers else "Not found")
    t.add_row("Ping 8.8.8.8", "[green]OK[/green]" if ping_ip_ok else "[red]FAIL[/red]")
    t.add_row("Ping google.com", "[green]OK[/green]" if ping_dns_ok else "[red]FAIL[/red]")
    print(t)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def updates(as_json):
    """List pending DNF updates."""
    r = subprocess.run(
        ["dnf", "check-update", "--quiet"],
        capture_output=True, text=True, check=False,
    )
    output = (r.stdout or "").strip()
    packages = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "." in parts[0]:
            pkg_name = parts[0].rsplit(".", 1)[0]
            new_ver = parts[1]
            # Try to get current version
            cur = run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", pkg_name])
            if "not installed" in cur:
                cur = "-"
            packages.append({"name": parts[0], "current": cur, "new": new_ver})

    if as_json:
        print(json.dumps({"count": len(packages), "packages": packages}, ensure_ascii=False, indent=2))
        return

    t = Table(title="Fedora Care • Updates", show_lines=True)
    t.add_column("Package", style="bold")
    t.add_column("Current Version")
    t.add_column("New Version")
    for p in packages:
        t.add_row(p["name"], p["current"], p["new"])
    print(t)
    print(f"\n[bold]{len(packages)}[/bold] pending update(s).")


@cli.command()
@click.option("--dest", default=None, help="Backup destination directory.")
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def backup(dest, as_json):
    """Backup important config files."""
    if dest is None:
        dest = os.path.join(
            Path.home(), "fedcare-backup", datetime.now().strftime("%Y%m%d-%H%M%S")
        )

    targets = [
        "/etc/fstab",
        "/etc/hosts",
        "/etc/dnf/dnf.conf",
        "/etc/ssh/sshd_config",
        "/etc/default/grub",
        "/etc/NetworkManager/",
    ]

    os.makedirs(dest, exist_ok=True)
    results = []
    for src in targets:
        try:
            if os.path.isdir(src):
                dst = os.path.join(dest, src.lstrip("/"))
                shutil.copytree(src, dst, dirs_exist_ok=True)
                results.append({"path": src, "status": "OK"})
            elif os.path.isfile(src):
                dst = os.path.join(dest, src.lstrip("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                results.append({"path": src, "status": "OK"})
            else:
                results.append({"path": src, "status": "Not found"})
        except PermissionError:
            results.append({"path": src, "status": "Permission denied"})
        except Exception as e:
            results.append({"path": src, "status": str(e)})

    if as_json:
        print(json.dumps({"dest": dest, "files": results}, ensure_ascii=False, indent=2))
        return

    t = Table(title=f"Fedora Care • Backup → {dest}", show_lines=True)
    t.add_column("File", style="bold")
    t.add_column("Status")
    for r in results:
        color = "green" if r["status"] == "OK" else "red"
        t.add_row(r["path"], f"[{color}]{r['status']}[/{color}]")
    print(t)


@cli.command()
@click.option("--list", "list_backups", is_flag=True, help="List available backups.")
@click.option("--latest", is_flag=True, help="Restore from the most recent backup.")
@click.option("--source", default=None, help="Backup directory to restore from.")
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def restore(list_backups, latest, source, as_json):
    """Restore config files from a backup."""
    backup_base = os.path.join(Path.home(), "fedcare-backup")

    # List available backups
    if list_backups:
        if not os.path.isdir(backup_base):
            if as_json:
                print(json.dumps({"backups": [], "message": "No backups found"}, ensure_ascii=False, indent=2))
            else:
                print("[yellow]No backups found.[/yellow]")
            return

        backups = sorted(
            [d for d in os.listdir(backup_base) if os.path.isdir(os.path.join(backup_base, d))],
            reverse=True
        )

        if as_json:
            backup_info = []
            for b in backups:
                path = os.path.join(backup_base, b)
                file_count = sum(len(files) for _, _, files in os.walk(path))
                backup_info.append({"name": b, "path": path, "files": file_count})
            print(json.dumps({"backups": backup_info}, ensure_ascii=False, indent=2))
            return

        if not backups:
            print("[yellow]No backups found.[/yellow]")
            return

        t = Table(title="Fedora Care • Available Backups", show_lines=True)
        t.add_column("Backup", style="bold")
        t.add_column("Path")
        t.add_column("Files")
        for b in backups:
            path = os.path.join(backup_base, b)
            file_count = sum(len(files) for _, _, files in os.walk(path))
            t.add_row(b, path, str(file_count))
        print(t)
        print(f"\nTo restore: [bold]fedcare restore --source {backups[0]}[/bold]")
        return

    # Determine source directory
    if latest:
        if not os.path.isdir(backup_base):
            print("[red]No backups found.[/red]")
            return
        backups = sorted(
            [d for d in os.listdir(backup_base) if os.path.isdir(os.path.join(backup_base, d))],
            reverse=True
        )
        if not backups:
            print("[red]No backups found.[/red]")
            return
        source = backups[0]

    if source is None:
        if as_json:
            print(json.dumps({"error": "No source specified. Use --list, --latest, or --source"}, ensure_ascii=False, indent=2))
        else:
            print("[red]No source specified.[/red]")
            print("Usage:")
            print("  fedcare restore --list              # List available backups")
            print("  fedcare restore --latest            # Restore from most recent")
            print("  fedcare restore --source BACKUP     # Restore from specific backup")
        return

    # Resolve full path
    if os.path.isabs(source):
        source_path = source
    else:
        source_path = os.path.join(backup_base, source)

    if not os.path.isdir(source_path):
        if as_json:
            print(json.dumps({"error": f"Backup not found: {source_path}"}, ensure_ascii=False, indent=2))
        else:
            print(f"[red]Backup not found: {source_path}[/red]")
        return

    # Restore files
    results = []
    for root, dirs, files in os.walk(source_path):
        for f in files:
            src_file = os.path.join(root, f)
            rel_path = os.path.relpath(src_file, source_path)
            dst_file = "/" + rel_path

            try:
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                shutil.copy2(src_file, dst_file)
                results.append({"file": dst_file, "status": "OK"})
            except PermissionError:
                # Try with sudo
                cp_result = subprocess.run(
                    ["sudo", "cp", "-p", src_file, dst_file],
                    capture_output=True, text=True, check=False
                )
                if cp_result.returncode == 0:
                    results.append({"file": dst_file, "status": "OK (sudo)"})
                else:
                    results.append({"file": dst_file, "status": "Permission denied"})
            except Exception as e:
                results.append({"file": dst_file, "status": str(e)})

    if as_json:
        print(json.dumps({"source": source_path, "restored": results}, ensure_ascii=False, indent=2))
        return

    t = Table(title=f"Fedora Care • Restore ← {source_path}", show_lines=True)
    t.add_column("File", style="bold")
    t.add_column("Status")
    for r in results:
        color = "green" if "OK" in r["status"] else "red"
        t.add_row(r["file"], f"[{color}]{r['status']}[/{color}]")
    print(t)

    ok_count = sum(1 for r in results if "OK" in r["status"])
    print(f"\n[bold green]{ok_count}/{len(results)}[/bold green] files restored.")


@cli.command()
@click.option("--top", "top_n", default=10, show_default=True, help="Number of services to show.")
@click.option("--json", "as_json", is_flag=True, help="Output in JSON format.")
def startup(top_n, as_json):
    """Show slowest services at boot."""
    output = run(["systemd-analyze", "blame", "--no-pager"])
    items = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            items.append({"time": parts[0], "service": parts[1]})
        if len(items) >= top_n:
            break

    if as_json:
        print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
        return

    t = Table(title=f"Fedora Care • Startup (Top {top_n})", show_lines=True)
    t.add_column("Rank", style="bold", justify="right")
    t.add_column("Service")
    t.add_column("Time")
    for i, item in enumerate(items, 1):
        t.add_row(str(i), item["service"], item["time"])
    print(t)


if __name__ == "__main__":
    cli()
