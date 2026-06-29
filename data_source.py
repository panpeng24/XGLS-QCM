import time
import random
import socket
import csv
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
# 2. 文件回放 (IC6 / SQC-310)
# ---------------------------------------------------------
class IC6TxtReplay(QCMDataSource):
    CHANNEL_COUNT = 8
    FREQ_START_COL = 1
    ACTIVE_START_COL = 9
    DATE_COL = 17
    TIME_COL = 18

    def __init__(self, txt_file, channel=6, channels=None):
        self.txt_file = txt_file
        self.channels = self._normalize_channels(channels if channels is not None else [channel])
        self.channel = self.channels[0]
        self.rows = []
        self.index = 0

    @classmethod
    def _normalize_channel(cls, channel):
        try:
            channel = int(channel)
        except (TypeError, ValueError):
            channel = 6
        return min(max(channel, 1), cls.CHANNEL_COUNT)

    @classmethod
    def _normalize_channels(cls, channels):
        normalized = []
        for channel in channels or [6]:
            channel = cls._normalize_channel(channel)
            if channel not in normalized:
                normalized.append(channel)
        return normalized or [6]

    @classmethod
    def _parse_ic6_row(cls, cols):
        if len(cols) < cls.TIME_COL + 1:
            return None
        try:
            frequencies = [float(cols[cls.FREQ_START_COL + i]) for i in range(cls.CHANNEL_COUNT)]
            active_values = [float(cols[cls.ACTIVE_START_COL + i]) for i in range(cls.CHANNEL_COUNT)]
            ts = datetime.strptime(f"{cols[cls.DATE_COL]} {cols[cls.TIME_COL]}", "%m/%d/%Y %H:%M:%S").timestamp()
        except (ValueError, IndexError):
            return None
        return {"ts": ts, "frequencies": frequencies, "active_values": active_values}

    def connect(self):
        self.rows = []
        print(f"[IC6 File] Loading {self.txt_file}...")
        try:
            with open(self.txt_file, "r", encoding="utf-8", errors='ignore') as f:
                for line in f:
                    if line.startswith("IC6") or not line.strip():
                        continue
                    parsed = self._parse_ic6_row(line.split())
                    if parsed is not None:
                        self.rows.append(parsed)
            self.index = 0
            channel_text = ",".join(f"CH{ch}" for ch in self.channels)
            print(f"[IC6 File] Loaded {len(self.rows)} points from {channel_text}.")
        except FileNotFoundError:
            raise FileNotFoundError(f"Cannot find file: {self.txt_file}")

    def read(self):
        if self.index >= len(self.rows):
            return None
        row = self.rows[self.index]
        self.index += 1
        selected_index = self.channel - 1
        return {
            "timestamp": row["ts"],
            "frequency": row["frequencies"][selected_index],
            "source_format": "IC6",
            "channel": self.channel,
            "selected_channels": self.channels,
            "frequencies": row["frequencies"],
            "active_values": row["active_values"],
        }


class SQC310CSVReplay(QCMDataSource):
    SENSOR_COUNT = 8

    def __init__(self, csv_file, sensor=1):
        self.csv_file = csv_file
        self.sensor = self._normalize_sensor(sensor)
        self.rows = []
        self.index = 0
        self.start_ts = None
        self.header = []

    @classmethod
    def _normalize_sensor(cls, sensor):
        try:
            sensor = int(sensor)
        except (TypeError, ValueError):
            sensor = 1
        return min(max(sensor, 1), cls.SENSOR_COUNT)

    @staticmethod
    def _parse_start_line(line):
        if "Start:" not in line or "Date:" not in line or "Time:" not in line:
            return None
        parts = line.replace("Start:", "").replace("Date:", " Date: ").replace("Time:", " Time: ").split()
        try:
            date_text = parts[parts.index("Date:") + 1]
            time_text = parts[parts.index("Time:") + 1]
            return datetime.strptime(f"{date_text} {time_text}", "%Y/%m/%d %H:%M:%S").timestamp()
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _to_float(value):
        return float(str(value).strip())

    @staticmethod
    def _header_index(header, name):
        target = name.lower()
        for idx, col in enumerate(header):
            if col.strip().lower() == target:
                return idx
        return None

    @classmethod
    def _extract_sensor_groups(cls, row):
        stripped = [col.strip() for col in row]
        try:
            marker = next(i for i, col in enumerate(stripped) if col.lower().startswith("sensors"))
        except StopIteration:
            return [], [], []
        rates, thicknesses, frequencies = [], [], []
        start = marker + 1
        for sensor_idx in range(cls.SENSOR_COUNT):
            base = start + sensor_idx * 3
            if base + 2 >= len(stripped):
                break
            try:
                rates.append(cls._to_float(stripped[base]))
                thicknesses.append(cls._to_float(stripped[base + 1]))
                frequencies.append(cls._to_float(stripped[base + 2]))
            except ValueError:
                rates.append(0.0)
                thicknesses.append(0.0)
                frequencies.append(0.0)
        return rates, thicknesses, frequencies

    @staticmethod
    def _first_valid_frequency(frequencies, preferred_index=0):
        if 0 <= preferred_index < len(frequencies) and frequencies[preferred_index] > 0:
            return frequencies[preferred_index]
        for frequency in frequencies:
            if frequency > 0:
                return frequency
        return None

    def _parse_data_row(self, row):
        if len(row) < 3:
            return None
        try:
            elapsed_s = self._to_float(row[0])
        except ValueError:
            return None

        sensor_rates, sensor_thicknesses, sensor_frequencies = self._extract_sensor_groups(row)
        freq_idx = self._header_index(self.header, f"Sens{self.sensor}Freq") if self.header else None
        rate_idx = self._header_index(self.header, f"Sens{self.sensor}Rate") if self.header else None
        thk_idx = self._header_index(self.header, f"Sens{self.sensor}Thk") if self.header else None

        selected_freq = None
        try:
            selected_freq = self._to_float(row[freq_idx]) if freq_idx is not None else sensor_frequencies[self.sensor - 1]
        except (ValueError, IndexError):
            pass
        if selected_freq is None or selected_freq == 0.0:
            selected_freq = self._first_valid_frequency(sensor_frequencies, preferred_index=self.sensor - 1)
        if selected_freq is None:
            return None

        selected_rate = None
        selected_thickness = None
        try:
            selected_rate = self._to_float(row[rate_idx]) if rate_idx is not None else sensor_rates[self.sensor - 1]
            selected_thickness = self._to_float(row[thk_idx]) if thk_idx is not None else sensor_thicknesses[self.sensor - 1]
        except (ValueError, IndexError):
            pass

        ts = (self.start_ts + elapsed_s) if self.start_ts is not None else elapsed_s
        return {
            "ts": ts,
            "elapsed_s": elapsed_s,
            "frequency": selected_freq,
            "sensor_rates": sensor_rates,
            "sensor_thicknesses": sensor_thicknesses,
            "sensor_frequencies": sensor_frequencies,
            "selected_rate": selected_rate,
            "selected_thickness": selected_thickness,
            "phase": row[1].strip() if len(row) > 1 else "",
        }

    def connect(self):
        self.rows = []
        self.header = []
        self.start_ts = None
        print(f"[SQC-310 File] Loading {self.csv_file}...")
        try:
            with open(self.csv_file, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
                for raw_line in f:
                    if self.start_ts is None:
                        self.start_ts = self._parse_start_line(raw_line)
                    if raw_line.lstrip().lower().startswith("time,"):
                        self.header = [col.strip() for col in next(csv.reader([raw_line]))]
                        break
                reader = csv.reader(f)
                for row in reader:
                    parsed = self._parse_data_row(row)
                    if parsed is not None:
                        self.rows.append(parsed)
            self.index = 0
            print(f"[SQC-310 File] Loaded {len(self.rows)} points from Sens{self.sensor}.")
        except FileNotFoundError:
            raise FileNotFoundError(f"Cannot find file: {self.csv_file}")

    def read(self):
        if self.index >= len(self.rows):
            return None
        row = self.rows[self.index]
        self.index += 1
        return {
            "timestamp": row["ts"],
            "elapsed_s": row["elapsed_s"],
            "frequency": row["frequency"],
            "source_format": "SQC-310",
            "channel": self.sensor,
            "phase": row["phase"],
            "sensor_rates": row["sensor_rates"],
            "sensor_thicknesses": row["sensor_thicknesses"],
            "sensor_frequencies": row["sensor_frequencies"],
            "selected_sensor_rate": row["selected_rate"],
            "selected_sensor_thickness": row["selected_thickness"],
        }


class AutoQCMFileReplay(QCMDataSource):
    def __init__(self, file_path, ic6_channel=6, sqc_sensor=1, file_format="Auto", ic6_channels=None):
        self.file_path = file_path
        self.ic6_channel = ic6_channel
        self.ic6_channels = IC6TxtReplay._normalize_channels(ic6_channels if ic6_channels is not None else [ic6_channel])
        self.sqc_sensor = sqc_sensor
        self.file_format = file_format
        self.delegate = None

    def _detect_format(self):
        if self.file_format in ("IC6", "SQC-310"):
            return self.file_format
        try:
            with open(self.file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                sample = "".join(f.readline() for _ in range(20)).lower()
        except FileNotFoundError:
            raise FileNotFoundError(f"Cannot find file: {self.file_path}")
        if "sqc" in sample or "sens1freq" in sample or "start:" in sample:
            return "SQC-310"
        return "IC6"

    def connect(self):
        detected = self._detect_format()
        if detected == "SQC-310":
            sensor = 1 if self.file_format == "Auto" and int(self.sqc_sensor) == 6 else self.sqc_sensor
            self.delegate = SQC310CSVReplay(self.file_path, sensor=sensor)
        else:
            self.delegate = IC6TxtReplay(self.file_path, channel=self.ic6_channel, channels=self.ic6_channels)
        self.delegate.connect()

    def disconnect(self):
        if self.delegate:
            self.delegate.disconnect()

    def read(self):
        if not self.delegate:
            return None
        return self.delegate.read()

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
