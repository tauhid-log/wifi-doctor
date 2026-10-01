from flask import Flask, render_template, jsonify
import subprocess
import platform
import re
import socket
import time
import sqlite3
import urllib.request
import json
from datetime import datetime

app = Flask(__name__)

DB_PATH = "wifi_doctor.db"
SESSION_START = time.time()


# ============================================================
# DATABASE
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            test_type TEXT,
            success INTEGER,
            score INTEGER,
            data TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_test(test_type, success, score, data):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO tests (timestamp, test_type, success, score, data) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), test_type, 1 if success else 0, score, json.dumps(data, default=str))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")


def get_history(limit=20):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT timestamp, test_type, success, score, data FROM tests ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        result = []
        for row in rows:
            result.append({
                "timestamp": row[0],
                "test_type": row[1],
                "success": bool(row[2]),
                "score": row[3],
                "data": json.loads(row[4]) if row[4] else {}
            })
        return result
    except Exception as e:
        print(f"[DB READ ERROR] {e}")
        return []


# ============================================================
# CORE FUNCTIONS
# ============================================================

def ping_host(host="8.8.8.8", count=4):
    system = platform.system().lower()
    param = "-n" if system == "windows" else "-c"
    try:
        result = subprocess.run(
            ["ping", param, str(count), host],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        latency = None
        if system == "windows":
            match = re.search(r"Average = (\d+)ms", output)
            if match:
                latency = float(match.group(1))
            else:
                match = re.search(r"time[=<]([\d.]+)ms", output)
                if match:
                    latency = float(match.group(1))
        else:
            match = re.search(r"min/avg/max.*= [\d.]+/([\d.]+)/", output)
            if match:
                latency = float(match.group(1))
        loss = None
        match = re.search(r"(\d+)% packet loss", output)
        if match:
            loss = int(match.group(1))
        return {"success": True, "host": host, "latency_ms": latency,
                "packet_loss_percent": loss, "count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_wifi_info():
    system = platform.system().lower()
    if system != "windows":
        return {"success": False, "error": "WiFi info only on Windows"}
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout
        info = {}
        patterns = {
            "ssid": r"SSID\s*:\s*(.+)",
            "signal": r"Signal\s*:\s*(\d+)%",
            "channel": r"Channel\s*:\s*(\d+)",
            "radio": r"Radio type\s*:\s*(.+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                value = match.group(1).strip()
                if key in ("signal", "channel"):
                    value = int(value)
                info[key] = value
        if not info:
            return {"success": False, "error": "No WiFi info found"}
        return {"success": True, **info}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_gateway_ip():
    system = platform.system().lower()
    try:
        if system == "windows":
            result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
            match = re.search(r"Default Gateway.*?:\s*([\d.]+)", result.stdout)
            if match:
                return match.group(1)
        else:
            result = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=5)
            match = re.search(r"default via ([\d.]+)", result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def get_public_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5) as r:
            data = json.loads(r.read())
            return data.get("ip")
    except Exception:
        return None


def get_isp_info():
    try:
        with urllib.request.urlopen("http://ip-api.com/json/", timeout=5) as r:
            data = json.loads(r.read())
            return {
                "isp": data.get("isp"),
                "city": data.get("city"),
                "region": data.get("regionName"),
                "country": data.get("country"),
                "timezone": data.get("timezone")
            }
    except Exception:
        return {"isp": None, "city": None, "region": None, "country": None, "timezone": None}


def get_session_uptime():
    elapsed = time.time() - SESSION_START
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_packet_loss(host="8.8.8.8", count=10):
    system = platform.system().lower()
    param = "-n" if system == "windows" else "-c"
    try:
        result = subprocess.run(
            ["ping", param, str(count), host],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout
        loss = None
        match = re.search(r"(\d+)% packet loss", output)
        if match:
            loss = int(match.group(1))
        latency = None
        if system == "windows":
            match = re.search(r"Average = (\d+)ms", output)
            if match:
                latency = float(match.group(1))
        return {"success": True, "host": host, "packet_loss_percent": loss,
                "latency_ms": latency, "count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_dns_servers():
    system = platform.system().lower()
    try:
        if system == "windows":
            result = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, timeout=5)
            return re.findall(r"DNS Servers.*?:\s*([\d.]+)", result.stdout)
    except Exception:
        pass
    return []


def dns_lookup_time(domain="google.com"):
    try:
        start = time.time()
        socket.gethostbyname(domain)
        elapsed = (time.time() - start) * 1000
        return {"success": True, "domain": domain, "time_ms": round(elapsed, 2)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def gateway_health():
    gateway = get_gateway_ip()
    if not gateway:
        return {"success": False, "error": "Gateway not found"}
    ping_result = ping_host(gateway, 4)
    return {
        "success": ping_result.get("success", False),
        "gateway": gateway,
        "latency_ms": ping_result.get("latency_ms"),
        "packet_loss_percent": ping_result.get("packet_loss_percent")
    }


def speed_test():
    try:
        import speedtest
        st = speedtest.Speedtest()
        st.get_best_server()
        download = st.download() / 1_000_000
        upload = st.upload() / 1_000_000
        ping = st.results.ping
        return {
            "success": True,
            "download_mbps": round(download, 2),
            "upload_mbps": round(upload, 2),
            "ping_ms": round(ping, 2),
            "server": st.results.server.get("name", "Unknown"),
            "isp": st.results.client.get("isp", "Unknown")
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def connection_info():
    wifi = get_wifi_info()
    gateway = get_gateway_ip()
    local_ip = get_local_ip()
    return {
        "success": True,
        "ssid": wifi.get("ssid"),
        "signal": wifi.get("signal"),
        "channel": wifi.get("channel"),
        "radio": wifi.get("radio"),
        "local_ip": local_ip,
        "gateway": gateway,
        "uptime": get_session_uptime()
    }


def more_info():
    return {
        "success": True,
        "public_ip": get_public_ip(),
        "isp_info": get_isp_info()
    }


# ============================================================
# DIAGNOSIS
# ============================================================

def calculate_score(results):
    score = 100

    router = results.get("router") or {}
    rl = router.get("latency_ms")
    if isinstance(rl, (int, float)) and rl > 5:
        score -= min(20, (rl - 5) * 2)

    internet = results.get("internet") or {}
    il = internet.get("latency_ms")
    if isinstance(il, (int, float)) and il > 30:
        score -= min(15, (il - 30) / 5)

    loss = results.get("loss") or {}
    pl = loss.get("packet_loss_percent")
    if isinstance(pl, (int, float)):
        score -= min(30, pl * 5)

    dns = results.get("dns") or {}
    dt = dns.get("time_ms")
    if isinstance(dt, (int, float)) and dt > 50:
        score -= min(10, (dt - 50) / 10)

    wifi = results.get("wifi") or {}
    sig = wifi.get("signal")
    if isinstance(sig, (int, float)) and sig < 80:
        score -= min(20, (80 - sig) / 2)

    return max(0, min(100, int(score)))


def generate_insights(results):
    insights = []

    router = results.get("router") or {}
    rl = router.get("latency_ms")
    if isinstance(rl, (int, float)):
        if rl > 20:
            insights.append({"type": "warning", "icon": "🏠",
                             "text": f"Router latency is high ({rl} ms). Try restarting your router."})
        elif rl < 5:
            insights.append({"type": "success", "icon": "✅",
                             "text": f"Router latency is excellent ({rl} ms)."})

    internet = results.get("internet") or {}
    il = internet.get("latency_ms")
    if isinstance(il, (int, float)) and il > 100:
        insights.append({"type": "warning", "icon": "🌐",
                         "text": f"Internet latency is high ({il} ms). Contact your ISP."})

    loss = results.get("loss") or {}
    pl = loss.get("packet_loss_percent")
    if isinstance(pl, (int, float)):
        if pl > 5:
            insights.append({"type": "danger", "icon": "📉",
                             "text": f"High packet loss ({pl}%). Connection is unstable."})
        elif pl == 0:
            insights.append({"type": "success", "icon": "✅",
                             "text": "No packet loss detected."})

    dns = results.get("dns") or {}
    dt = dns.get("time_ms")
    if isinstance(dt, (int, float)):
        if dt > 100:
            insights.append({"type": "warning", "icon": "🔍",
                             "text": f"DNS is slow ({dt} ms). Try 1.1.1.1 or 8.8.8.8."})
        elif dt < 20:
            insights.append({"type": "success", "icon": "✅",
                             "text": f"DNS is fast ({dt} ms)."})

    wifi = results.get("wifi") or {}
    sig = wifi.get("signal")
    if isinstance(sig, (int, float)):
        if sig < 50:
            insights.append({"type": "warning", "icon": "📶",
                             "text": f"Weak WiFi signal ({sig}%). Move closer to router."})
        elif sig >= 80:
            insights.append({"type": "success", "icon": "✅",
                             "text": f"Strong WiFi signal ({sig}%)."})

    return insights


def full_diagnosis():
    try:
        results = {}

        wifi = get_wifi_info()
        results["wifi"] = wifi
        save_test("wifi", wifi.get("success", False), 0, wifi)

        gateway = get_gateway_ip() or "192.168.1.1"
        router_ping = ping_host(gateway, 4)
        router_ping["host"] = gateway
        results["router"] = router_ping
        save_test("router", router_ping.get("success", False), 0, router_ping)

        internet_ping = ping_host("8.8.8.8", 4)
        results["internet"] = internet_ping
        save_test("internet", internet_ping.get("success", False), 0, internet_ping)

        loss = get_packet_loss("8.8.8.8", 10)
        results["loss"] = loss
        save_test("loss", loss.get("success", False), 0, loss)

        dns = dns_lookup_time("google.com")
        dns["dns_servers"] = get_dns_servers()
        results["dns"] = dns
        save_test("dns", dns.get("success", False), 0, dns)

        score = calculate_score(results)
        insights = generate_insights(results)

        save_test("full_diagnosis", True, score, {"score": score, "insights": insights})

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "score": score,
            "results": results,
            "insights": insights
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/wifi-info")
def api_wifi_info():
    return jsonify(get_wifi_info())


@app.route("/api/router-ping")
def api_router_ping():
    gateway = get_gateway_ip()
    if not gateway:
        return jsonify({"success": False, "error": "Gateway not found"})
    result = ping_host(gateway, 4)
    result["host"] = gateway
    return jsonify(result)


@app.route("/api/internet-ping")
def api_internet_ping():
    return jsonify(ping_host("8.8.8.8", 4))


@app.route("/api/packet-loss")
def api_packet_loss():
    return jsonify(get_packet_loss("8.8.8.8", 10))


@app.route("/api/dns-test")
def api_dns_test():
    servers = get_dns_servers()
    result = dns_lookup_time("google.com")
    result["dns_servers"] = servers
    return jsonify(result)


@app.route("/api/gateway-health")
def api_gateway_health():
    return jsonify(gateway_health())


@app.route("/api/speed-test")
def api_speed_test():
    return jsonify(speed_test())


@app.route("/api/connection-info")
def api_connection_info():
    return jsonify(connection_info())


@app.route("/api/more-info")
def api_more_info():
    return jsonify(more_info())


@app.route("/api/full-diagnosis")
def api_full_diagnosis():
    return jsonify(full_diagnosis())


@app.route("/api/history")
def api_history():
    return jsonify({"success": True, "history": get_history(20)})


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)