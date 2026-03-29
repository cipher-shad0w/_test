# /// script
# requires-python = ">=3.9"
# dependencies = ["pymodbus>=3.6"]
# ///
"""Sungrow SH5.0RT Steuerung per Modbus TCP.

Nutzung:
    uv run sungrow_control.py status                         # Status anzeigen
    uv run sungrow_control.py offgrid                        # Netzunabhaengigen Modus aktivieren
    uv run sungrow_control.py ongrid                         # Netzunabhaengigen Modus deaktivieren
    uv run sungrow_control.py status --host 10.10.100.254    # Direkt-LAN
"""
import argparse
import struct
import sys

from pymodbus.client import ModbusTcpClient
from pymodbus.framer import FramerType

DEFAULT_HOST = "192.168.178.55"
PORT = 502
SLAVE_ID = 1

# --- Register-Definitionen (SH-RT Series) ---

# Holding Register 13074: Netzunabhaengiger Modus (Off-Grid Option)
REG_OFFGRID_ENABLE = 13074
OFFGRID_ON = 0xAA   # 170
OFFGRID_OFF = 0x55   # 85

# Holding Register 13099: Backup Reserved SOC
REG_BACKUP_SOC = 13099

# Holding Register 13049: EMS Mode
REG_EMS_MODE = 13049

EMS_MODES = {
    0: "Eigenverbrauch (Self-consumption)",
    1: "Erzwungen (Forced)",
    2: "Backup",
    3: "Einspeise-Prioritaet (Feed-in priority)",
}

RUNNING_STATES = {
    0x0000: "Stop",
    0x0002: "Standby",
    0x0008: "Betrieb (Running)",
    0x0010: "Fehler (Fault)",
    0x0020: "Initial Standby",
}


def connect(host: str) -> ModbusTcpClient:
    client = ModbusTcpClient(host=host, port=PORT, framer=FramerType.SOCKET, timeout=5)
    if not client.connect():
        print(f"Fehler: Konnte nicht zu {host}:{PORT} verbinden.")
        sys.exit(1)
    return client


def read_input_u16(client: ModbusTcpClient, address: int) -> int:
    result = client.read_input_registers(address=address, count=1, device_id=SLAVE_ID)
    if result.isError():
        raise RuntimeError(f"Fehler beim Lesen von Input-Register {address}: {result}")
    return result.registers[0]


def read_input_s16(client: ModbusTcpClient, address: int) -> int:
    raw = read_input_u16(client, address)
    return struct.unpack(">h", struct.pack(">H", raw))[0]


def read_input_s32(client: ModbusTcpClient, address: int) -> int:
    result = client.read_input_registers(address=address, count=2, device_id=SLAVE_ID)
    if result.isError():
        raise RuntimeError(f"Fehler beim Lesen von Input-Register {address}: {result}")
    high, low = result.registers
    raw = (high << 16) | low
    return struct.unpack(">i", struct.pack(">I", raw))[0]


def read_holding_u16(client: ModbusTcpClient, address: int) -> int:
    result = client.read_holding_registers(address=address, count=1, device_id=SLAVE_ID)
    if result.isError():
        raise RuntimeError(f"Fehler beim Lesen von Holding-Register {address}: {result}")
    return result.registers[0]


def write_holding_u16(client: ModbusTcpClient, address: int, value: int) -> None:
    result = client.write_register(address=address, value=value, device_id=SLAVE_ID)
    if result.isError():
        raise RuntimeError(f"Fehler beim Schreiben von Register {address}={value}: {result}")


def cmd_status(client: ModbusTcpClient) -> None:
    print("=== Sungrow SH5.0RT Status ===\n")

    # Netzunabhaengiger Modus
    offgrid = read_holding_u16(client, REG_OFFGRID_ENABLE)
    if offgrid == OFFGRID_ON:
        offgrid_str = "AN"
    elif offgrid == OFFGRID_OFF:
        offgrid_str = "AUS"
    else:
        offgrid_str = f"Unbekannt (0x{offgrid:04X})"
    print(f"Netzunabh. Modus: {offgrid_str}")

    # EMS Mode
    ems_mode = read_holding_u16(client, REG_EMS_MODE)
    print(f"EMS-Modus:        {EMS_MODES.get(ems_mode, f'Unbekannt ({ems_mode})')}")

    # Backup Reserved SOC
    backup_soc = read_holding_u16(client, REG_BACKUP_SOC)
    if backup_soc != 0xFFFF:
        print(f"Backup-Reserve:   {backup_soc}%")

    # Running State
    running = read_input_u16(client, 13000)
    print(f"Betriebszustand:  {RUNNING_STATES.get(running, f'Unbekannt (0x{running:04X})')}")

    # Battery SOC
    soc = read_input_u16(client, 13022) / 10.0
    print(f"Batterie-SOC:     {soc:.1f}%")

    # Battery Power
    bat_power = read_input_s16(client, 13020)
    direction = "Laden" if bat_power > 0 else "Entladen" if bat_power < 0 else "Idle"
    print(f"Batterie-Leistung:{abs(bat_power):>6d} W ({direction})")

    # Total Active Power
    total_power = read_input_s32(client, 13008)
    print(f"Gesamt-Leistung:  {total_power:>6d} W")

    # Grid Power
    grid_power = read_input_s32(client, 13034)
    grid_dir = "Bezug" if grid_power > 0 else "Einspeisung" if grid_power < 0 else "Idle"
    print(f"Netz-Leistung:    {abs(grid_power):>6d} W ({grid_dir})")


def cmd_offgrid(client: ModbusTcpClient) -> None:
    print("Aktiviere netzunabhaengigen Modus (Register 13074 = 0xAA)...")
    write_holding_u16(client, REG_OFFGRID_ENABLE, OFFGRID_ON)
    val = read_holding_u16(client, REG_OFFGRID_ENABLE)
    if val == OFFGRID_ON:
        print("Erfolgreich! Netzunabhaengiger Modus ist jetzt AN.")
    else:
        print(f"Warnung: Register 13074 = 0x{val:04X} (erwartet: 0xAA)")


def cmd_ongrid(client: ModbusTcpClient) -> None:
    print("Deaktiviere netzunabhaengigen Modus (Register 13074 = 0x55)...")
    write_holding_u16(client, REG_OFFGRID_ENABLE, OFFGRID_OFF)
    val = read_holding_u16(client, REG_OFFGRID_ENABLE)
    if val == OFFGRID_OFF:
        print("Erfolgreich! Netzunabhaengiger Modus ist jetzt AUS.")
    else:
        print(f"Warnung: Register 13074 = 0x{val:04X} (erwartet: 0x55)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sungrow SH5.0RT Steuerung")
    parser.add_argument("command", choices=["status", "offgrid", "ongrid"],
                        help="status=Anzeigen, offgrid=Netzunabh. Modus AN, ongrid=Netzunabh. Modus AUS")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"IP-Adresse des Sungrow (Default: {DEFAULT_HOST})")
    args = parser.parse_args()

    client = connect(args.host)
    try:
        {"status": cmd_status, "offgrid": cmd_offgrid, "ongrid": cmd_ongrid}[args.command](client)
    except RuntimeError as e:
        print(f"\nFehler: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
