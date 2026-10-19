import argparse
import socket
import ssl
import sys
import time
import urllib.request

CLR_RESET = "\033[0m"
CLR_CYAN = "\033[38;2;0;245;212m"
CLR_GREEN = "\033[38;2;40;201;64m"
CLR_YELLOW = "\033[38;2;254;188;46m"
CLR_RED = "\033[38;2;255;95;87m"
CLR_BLUE = "\033[38;2;80;160;255m"
CLR_GRAY = "\033[38;2;120;140;160m"
CLR_BOLD = "\033[1m"

def probe_worker_websocket(endpoint_ip, host_header, path="/vless", port=443, timeout=4.0):
    start_tcp = time.time()
    try:
        sock = socket.create_connection((endpoint_ip, port), timeout=timeout)
        tcp_ms = (time.time() - start_tcp) * 1000.0
    except Exception as e:
        return {"status": "FAIL", "stage": "TCP", "error": str(e), "tcp_ms": 0.0}

    start_tls = time.time()
    try:
        ctx = ssl.create_default_context()
        ssock = ctx.wrap_socket(sock, server_hostname=host_header)
        tls_ms = (time.time() - start_tls) * 1000.0
    except Exception as e:
        sock.close()
        return {"status": "FAIL", "stage": "TLS", "error": str(e), "tcp_ms": tcp_ms, "tls_ms": 0.0}

    start_ws = time.time()
    try:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        ssock.sendall(req.encode("utf-8"))
        resp = ssock.recv(1024).decode("utf-8", errors="ignore")
        ws_ms = (time.time() - start_ws) * 1000.0
        ssock.close()

        first_line = resp.split("\r\n")[0] if resp else "EMPTY"
        colo = "UNKNOWN"
        for line in resp.split("\r\n"):
            if "cf-ray" in line.lower():
                parts = line.split("-")
                if len(parts) > 1:
                    colo = parts[-1].strip()

        if "101" in first_line:
            return {
                "status": "READY",
                "code": 101,
                "tcp_ms": round(tcp_ms, 1),
                "tls_ms": round(tls_ms, 1),
                "ws_ms": round(ws_ms, 1),
                "colo": colo,
                "state": "UPGRADED (WebSocket Active)"
            }
        elif "200" in first_line or "404" in first_line:
            return {
                "status": "PASS",
                "code": int(first_line.split()[1]) if len(first_line.split()) > 1 else 200,
                "tcp_ms": round(tcp_ms, 1),
                "tls_ms": round(tls_ms, 1),
                "ws_ms": round(ws_ms, 1),
                "colo": colo,
                "state": f"HTTP_RESPONSE ({first_line[:15]})"
            }
        else:
            return {
                "status": "WARN",
                "code": 0,
                "tcp_ms": round(tcp_ms, 1),
                "tls_ms": round(tls_ms, 1),
                "ws_ms": round(ws_ms, 1),
                "colo": colo,
                "state": f"PEER_RESPONSE ({first_line[:20]})"
            }
    except Exception as e:
        try:
            ssock.close()
        except Exception:
            pass
        return {"status": "FAIL", "stage": "WS", "error": str(e), "tcp_ms": tcp_ms, "tls_ms": tls_ms}

def main():
    parser = argparse.ArgumentParser(
        description="V7LTHRONYX Cloudflare Workers VLESS WebSocket Prober"
    )
    parser.add_argument("-w", "--worker", default="cloudflare.com", help="Worker hostname or custom domain (default: cloudflare.com)")
    parser.add_argument("-i", "--ip", default="104.16.132.229", help="Clean Anycast IP used as connection destination (default: 104.16.132.229)")
    parser.add_argument("-p", "--port", type=int, default=443, help="Port (default: 443)")
    parser.add_argument("--path", default="/vless", help="WebSocket proxy path (default: /vless)")
    parser.add_argument("--count", type=int, default=3, help="Number of probe iterations (default: 3)")
    args = parser.parse_args()

    print(f"\n{CLR_CYAN}{CLR_BOLD}═══════════════════════════════════════════════════════════════════════════════{CLR_RESET}")
    print(f"{CLR_CYAN}{CLR_BOLD}  V7LTHRONYX CLOUDFLARE WORKERS VLESS WEBSOCKET PROBER v1.0.0{CLR_RESET}")
    print(f"{CLR_CYAN}{CLR_BOLD}  Serverless Edge Proxy Diagnostics | Clean IP Ingress Verification{CLR_RESET}")
    print(f"{CLR_CYAN}{CLR_BOLD}═══════════════════════════════════════════════════════════════════════════════{CLR_RESET}\n")

    print(f"{CLR_BOLD}Worker Host:{CLR_RESET}      {args.worker}")
    print(f"{CLR_BOLD}Clean Anycast IP:{CLR_RESET} {args.ip}:{args.port}")
    print(f"{CLR_BOLD}WS Path:{CLR_RESET}          {args.path}")
    print(f"{CLR_BOLD}Iterations:{CLR_RESET}       {args.count}\n")

    print(f"{CLR_CYAN}PROBING WEBSOCKET UPGRADE ACROSS CLEAN EDGE...{CLR_RESET}")
    print("─" * 79)
    print(f"{'ITER':<6}{'TCP RTT':<12}{'TLS RTT':<12}{'WS UPGRADE':<14}{'COLO':<10}{'STATE'}")
    print("─" * 79)

    success_count = 0
    total_total_ms = 0.0

    for i in range(1, args.count + 1):
        res = probe_worker_websocket(args.ip, args.worker, args.path, args.port)
        if res["status"] in ("READY", "PASS", "WARN"):
            success_count += 1
            total_rtt = res["tcp_ms"] + res["tls_ms"] + res["ws_ms"]
            total_total_ms += total_rtt
            state_color = CLR_GREEN if res["status"] == "READY" else CLR_YELLOW
            print(f"#{i:<5}{res['tcp_ms']:>6.1f} ms  {res['tls_ms']:>6.1f} ms  {res['ws_ms']:>8.1f} ms    {res['colo']:<8}  {state_color}{res['state']}{CLR_RESET}")
        else:
            print(f"#{i:<5}{res.get('tcp_ms', 0):>6.1f} ms  {'FAIL':>8}  {'-':>10}    {'-':<8}  {CLR_RED}FAILED ({res.get('error','')[:20]}){CLR_RESET}")
        time.sleep(0.3)

    print("─" * 79)
    if success_count > 0:
        avg_total = total_total_ms / success_count
        print(f"\n{CLR_GREEN}{CLR_BOLD}[+] Edge WebSocket Handshake Verified:{CLR_RESET} {success_count}/{args.count} Success | Avg End-to-End Latency: {avg_total:.1f} ms\n")
    else:
        print(f"\n{CLR_RED}{CLR_BOLD}[-] WebSocket Probe Failed.{CLR_RESET}\n")

if __name__ == "__main__":
    main()
