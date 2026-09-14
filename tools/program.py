"""Prototype instruction encoder. All returned words are unsigned 32-bit values."""


def drive(value, enable, cycles):
    if not (0 <= value < 32 and 0 <= enable < 32 and 1 <= cycles <= 262144):
        raise ValueError("DRIVE needs 5-bit value/OE and 1..262144 cycles")
    return ((cycles - 1) << 10) | (enable << 5) | value


def wait_pin(pin, level, timeout=0):
    if not (0 <= pin <= 4 and level in (0, 1) and 0 <= timeout < 262144):
        raise ValueError("WAIT needs pin 0..4, level 0/1, timeout 0..262143")
    return 0x10000000 | (timeout << 10) | (level << 3) | pin


def jump(address):
    if not 0 <= address < 64:
        raise ValueError("JUMP address must be 0..63")
    return 0x20000000 | address


SAMPLE = 0x30000000
HALT = 0xF0000000
TRAP = 0xA0000000


def load_byte(value, count=8):
    if not (0 <= value < 256 and 0 <= count < 256):
        raise ValueError("LOAD requires byte and count in 0..255")
    return 0x40000000 | (count << 8) | value


def shift_out(pin, lsb_first=False, open_drain=False):
    if not 0 <= pin <= 4:
        raise ValueError("OUT lane must be 0..4")
    return 0x50000000 | (int(open_drain) << 4) | (int(lsb_first) << 3) | pin


def shift_in(pin, lsb_first=False):
    if not 0 <= pin <= 4:
        raise ValueError("IN lane must be 0..4")
    return 0x60000000 | (int(lsb_first) << 3) | pin


def djnz(address):
    if not 0 <= address < 64:
        raise ValueError("DJNZ address must be 0..63")
    return 0x70000000 | address


def branch_pin(pin, level, address):
    if not (0 <= pin <= 4 and level in (0, 1) and 0 <= address < 64):
        raise ValueError("BRANCH needs lane 0..4, level 0/1, address 0..63")
    return 0x80000000 | (address << 4) | (level << 3) | pin


def check_tx(pin):
    if not 0 <= pin <= 4:
        raise ValueError("CHECK_TX lane must be 0..4")
    return 0x90000000 | pin


def patch(mask, value, enable, cycles=1):
    if not (0 <= mask < 32 and 0 <= value < 32 and 0 <= enable < 32 and 1 <= cycles <= 8192):
        raise ValueError("PATCH needs 5-bit mask/value/OE and 1..8192 clocks")
    return 0xB0000000 | ((cycles - 1) << 15) | (mask << 10) | (enable << 5) | value


def hold(cycles):
    return patch(0, 0, 0, cycles)


def spi_transfer(byte, mode=0, lsb_first=False, half_period=5):
    """One full-duplex byte: SCK=0, MOSI=1, MISO=2, CSn=3. All four modes.

    Half-period is a minimum hold, not a uniform clock divider: instruction
    overhead lengthens phases. At least four clocks allow input synchronization.
    Read the receive byte via the halted result page.
    """
    if mode not in range(4) or not 4 <= half_period <= 8192:
        raise ValueError("SPI mode must be 0..3 and half_period 4..8192")
    cpol, cpha = mode >> 1, mode & 1
    words = [drive(8 | cpol, 11, half_period), load_byte(byte),
             patch(8, 0, 8, half_period)]
    loop = len(words)
    if cpha == 0:
        words += [shift_out(1, lsb_first), hold(half_period),
                  patch(1, 1 - cpol, 1, half_period), shift_in(2, lsb_first),
                  patch(1, cpol, 1, half_period)]
    else:
        words += [patch(1, 1 - cpol, 1), shift_out(1, lsb_first), hold(half_period),
                  patch(1, cpol, 1, half_period), shift_in(2, lsb_first)]
    words += [djnz(loop), patch(8, 8, 8, half_period), HALT]
    return words


def i2c_write(address, byte, half_period=50, timeout=2000):
    """7-bit address + one data byte, open-drain SCL=0 and SDA=1.

    Handles ACK/NACK, bounded stretching and CHECK_TX contention detection.
    Single-controller demonstration; not a complete multi-controller controller.
    """
    if not 0 <= address < 128 or not 4 <= half_period <= 8192 or not 1 <= timeout < 262144:
        raise ValueError("I2C needs 7-bit address, half_period 4..8192, timeout 1..262143")
    words = [drive(0, 0, half_period), wait_pin(0, 1, timeout), wait_pin(1, 1, timeout),
             patch(2, 0, 2, half_period), patch(1, 0, 1, half_period)]
    nack_branches = []
    for value in [address << 1, byte]:
        words.append(load_byte(value))
        loop = len(words)
        words += [shift_out(1, open_drain=True), hold(half_period),
                  patch(1, 0, 0, 4), wait_pin(0, 1, timeout), hold(half_period),
                  check_tx(1), patch(1, 0, 1, half_period), djnz(loop),
                  patch(2, 0, 0, half_period), patch(1, 0, 0, 4),
                  wait_pin(0, 1, timeout), hold(half_period), SAMPLE]
        nack_branches.append(len(words))
        words += [0, patch(1, 0, 1, half_period)]

    def stop():
        return [patch(2, 0, 2, half_period), patch(1, 0, 0, 4),
                wait_pin(0, 1, timeout), hold(half_period), patch(2, 0, 0, half_period)]

    words += stop() + [HALT]
    nack = len(words)
    words += [patch(1, 0, 1, half_period)] + stop() + [TRAP]
    for index in nack_branches:
        words[index] = branch_pin(1, 1, nack)
    encode(words)  # Enforce the physical instruction-store limit.
    return words


def uart_tx(byte, cycles_per_bit=87):
    """One 8N1 frame on lane 0, preceded by one idle bit; then release pins."""
    if not 0 <= byte < 256:
        raise ValueError("UART byte must be 0..255")
    levels = [1, 0] + [(byte >> bit) & 1 for bit in range(8)] + [1]
    return [drive(level, 1, cycles_per_bit) for level in levels] + [HALT]


def encode(words):
    if not 1 <= len(words) <= 64:
        raise ValueError("program must contain 1..64 instructions")
    return b"".join(word.to_bytes(4, "little") for word in words)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate protocol engine firmware")
    parser.add_argument("output", type=Path)
    parser.add_argument("--byte", type=lambda s: int(s, 0), default=0x55)
    parser.add_argument("--cycles", type=int, default=87)
    parser.add_argument("--protocol", choices=["uart", "spi", "i2c"], default="uart")
    parser.add_argument("--mode", type=int, default=0)
    parser.add_argument("--lsb-first", action="store_true")
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0x50)
    parser.add_argument("--half-period", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=2000)
    args = parser.parse_args()
    if args.protocol == "uart":
        words = uart_tx(args.byte, args.cycles)
    elif args.protocol == "spi":
        words = spi_transfer(args.byte, args.mode, args.lsb_first, args.half_period)
    else:
        words = i2c_write(args.address, args.byte, args.half_period, args.timeout)
    args.output.write_bytes(encode(words))
