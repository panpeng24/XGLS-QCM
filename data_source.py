import time
import random
import socket
from datetime import datetime


class QCMDataSource:
    def connect(self): pass

    def disconnect(self): pass

    def read(self): return None


# ---------------------------------------------------------
# 1. 模拟数据源
# ---------------------------------------------------------
class MockQCMStream(QCMDataSource):
    def __init__(self):
        self.start_time = None
        self.f0 = 6000000.0
        self.drift = 0.0

    def connect(self):
        self.start_time = time.time()
        self.drift = 0.0
        print("[Mock] Simulation started.")

    def read(self):
        if self.start_time is None: return None
        elapsed = time.time() - self.start_time
        if elapsed > 3: self.drift -= 0.8
        noise = random.uniform(-0.3, 0.3)
        freq = self.f0 + self.drift + noise

        # 这里的 sleep 保留，模拟真实硬件采样率，但在回放模式下不会用到这个类
        time.sleep(0.05)
        return {"timestamp": time.time(), "frequency": freq}


# ---------------------------------------------------------
# 2. 文件回放 (已优化：移除 sleep)
# ---------------------------------------------------------
class IC6TxtReplay(QCMDataSource):
    def __init__(self, txt_file):
        self.txt_file = txt_file
        self.rows = []
        self.index = 0

    def connect(self):
        self.rows = []
        print(f"[File] Loading {self.txt_file}...")
        try:
            with open(self.txt_file, "r", encoding="utf-8", errors='ignore') as f:
                for line in f:
                    if line.startswith("IC6") or not line.strip(): continue
                    cols = line.split()
                    if len(cols) < 19: continue
                    try:
                        freq = float(cols[6])
                        ts = datetime.strptime(f"{cols[17]} {cols[18]}", "%m/%d/%Y %H:%M:%S").timestamp()
                        self.rows.append({"ts": ts, "f": freq})
                    except:
                        continue
            self.index = 0
            print(f"[File] Loaded {len(self.rows)} points.")
        except FileNotFoundError:
            raise FileNotFoundError(f"Cannot find file: {self.txt_file}")

    def read(self):
        # --- 极速模式：不再在此处 Sleep ---
        if self.index >= len(self.rows): return None
        row = self.rows[self.index]
        self.index += 1
        return {"timestamp": row["ts"], "frequency": row["f"]}


# ---------------------------------------------------------
# 3. 以太网客户端
# ---------------------------------------------------------
class EthernetQCMClient(QCMDataSource):
    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = int(port)
        self.sock = None
        self.QUERY_CMD = b"GET_FREQ\n"

    def connect(self):
        print(f"[Ethernet] Connecting to {self.ip}:{self.port}...")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(3.0)
        self.sock.connect((self.ip, self.port))
        self.sock.settimeout(0.2)

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = None

    def read(self):
        if not self.sock: return None
        try:
            if self.QUERY_CMD: self.sock.sendall(self.QUERY_CMD)
            data = self.sock.recv(1024).decode('utf-8').strip()
            if not data: return None
            val_str = data.split()[-1]
            freq = float(val_str)
            return {"timestamp": time.time(), "frequency": freq}
        except Exception:
            return None
