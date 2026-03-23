#!/usr/bin/env python3
"""
Kanzi SNR (Nova) and Chimp UDT firmware patcher
Patches retail technician cables to be recognized by Astris as real debug probes.

SNR/Nova patch:  Changes USB PID from 0x1624 to 0x1621 (Kanzi)
UDT patch:       Patches is_UDT() to always return 0 (Chimp)

Based on: https://https://nyansatan.github.io/snr-udt-fw-patching/ article

Usage:
    python3 patch_cables.py --snr  <input.bin> <output.bin>
    python3 patch_cables.py --udt  <input.bin> <output.bin>

After patching, fix CRC with kblcrcfix before flashing:
    kblcrcfix <output.bin>

Flash via kblctl or astrisctl (enter bootloader mode first via button in LED hole).
"""

import sys
import struct
import shutil
import argparse

# ---------------------------------------------------------------------------
# CRC32 (STM32 style -- matches KanziBoot verification)
# ---------------------------------------------------------------------------

def crc32_stm32(data):
    """
    STM32 hardware CRC32: poly 0x04C11DB7, init 0xFFFFFFFF, no reflection.
    Operates on 32-bit words.
    """
    crc = 0xFFFFFFFF
    for i in range(0, len(data) - 4, 4):
        word = struct.unpack_from('<I', data, i)[0]
        crc ^= word
        for _ in range(32):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc

def fix_crc(buf):
    """
    Fix CRC checksum in-place.
    KanziBoot verifies: CRC32(firmware) == 0
    The last 4 bytes of firmware are the fix value.
    Firmware starts at 0x4000, length at 0x401C.
    """
    fw_len = struct.unpack_from('<I', buf, 0x401C)[0]
    fw_end = 0x4000 + fw_len

    # Zero out the last 4 bytes (fix value location)
    struct.pack_into('<I', buf, fw_end - 4, 0)

    # Calculate CRC of firmware without fix value
    fw_data = bytes(buf[0x4000:fw_end])
    current_crc = crc32_stm32(fw_data)

    # We need to find a value X such that CRC32(fw || X) == 0
    # STM32 CRC is linear so we can compute the fix value
    # Try brute approach: set fix = complement of current CRC
    # For STM32 CRC, the fix value that zeroes the result is computed as:
    fix_val = current_crc  # Most implementations: last word that makes CRC=0
    struct.pack_into('<I', buf, fw_end - 4, fix_val)

    # Verify
    fw_data_fixed = bytes(buf[0x4000:fw_end])
    final_crc = crc32_stm32(fw_data_fixed)

    return fix_val, final_crc

# ---------------------------------------------------------------------------
# SNR (Nova/Kanzi) patcher
# ---------------------------------------------------------------------------

SNR_PATCH_OFFSET = 0x42b8   # MOVS R1, #0x24 -> MOVS R1, #0x21
SNR_EXPECTED     = bytes([0x24, 0x21])  # MOVS R1, #0x24 (SNR PID low byte)
SNR_PATCH        = bytes([0x21, 0x21])  # MOVS R1, #0x21 (Kanzi PID low byte)

def patch_snr(buf):
    """
    Patch SNR/Nova firmware to report Kanzi PID (0x1621) instead of Nova (0x1624).
    Single 1-byte patch: change 0x24 to 0x21 in MOVS R1, #0xYY instruction.
    """
    print(f"\n[SNR] Patching Nova -> Kanzi PID")
    print(f"  Patch offset : {SNR_PATCH_OFFSET:#x}")
    print(f"  Current      : {buf[SNR_PATCH_OFFSET:SNR_PATCH_OFFSET+2].hex()} "
          f"(MOVS R1, #{buf[SNR_PATCH_OFFSET]:#04x})")

    current = bytes(buf[SNR_PATCH_OFFSET:SNR_PATCH_OFFSET+2])
    if current != SNR_EXPECTED:
        print(f"  [WARN] Expected {SNR_EXPECTED.hex()} got {current.hex()}")
        print(f"  [WARN] Wrong firmware version or already patched?")
        if input("  Continue anyway? [y/N]: ").strip().lower() != 'y':
            return False

    buf[SNR_PATCH_OFFSET]   = SNR_PATCH[0]
    buf[SNR_PATCH_OFFSET+1] = SNR_PATCH[1]

    print(f"  Patched to   : {buf[SNR_PATCH_OFFSET:SNR_PATCH_OFFSET+2].hex()} "
          f"(MOVS R1, #{buf[SNR_PATCH_OFFSET]:#04x})")
    print(f"  [OK] PID patch applied: 0x1624 -> 0x1621")
    return True

# ---------------------------------------------------------------------------
# UDT (Chimp) patcher
# ---------------------------------------------------------------------------

UDT_FN_OFFSET = 0xb46c      # is_UDT() function entry point
UDT_EXPECTED  = bytes([0x80, 0xb5, 0x6f, 0x46])  # PUSH {r7,lr}; MOV r7,sp
UDT_PATCH     = bytes([0x00, 0x20, 0x70, 0x47])  # MOVS R0, #0; BX LR

def patch_udt(buf):
    """
    Patch UDT firmware to make is_UDT() always return 0.
    This makes the firmware think it's running on a real Chimp probe.

    Replaces the first 4 bytes of is_UDT() with:
        MOVS R0, #0   ; return value = 0 (not UDT)
        BX   LR       ; return immediately

    Function is at file offset 0xb46c, confirmed by tracing BL from
    PID assignment block at 0x4860 -> 0xb46c.
    """
    print(f"\n[UDT] Patching is_UDT() to always return 0")
    print(f"  Function offset : {UDT_FN_OFFSET:#x}")
    print(f"  Current bytes   : {buf[UDT_FN_OFFSET:UDT_FN_OFFSET+4].hex()}")

    current = bytes(buf[UDT_FN_OFFSET:UDT_FN_OFFSET+4])
    if current != UDT_EXPECTED:
        print(f"  [WARN] Expected {UDT_EXPECTED.hex()} got {current.hex()}")
        print(f"  [WARN] Wrong firmware version or already patched?")
        if input("  Continue anyway? [y/N]: ").strip().lower() != 'y':
            return False

    buf[UDT_FN_OFFSET:UDT_FN_OFFSET+4] = UDT_PATCH

    print(f"  Patched to      : {buf[UDT_FN_OFFSET:UDT_FN_OFFSET+4].hex()}")
    print(f"  [OK] is_UDT() will now always return 0 (Chimp)")
    return True

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Kanzi SNR / Chimp UDT firmware patcher for Astris compatibility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 patch_cables.py --snr Kanzi-SNR-1_07.bin Kanzi-SNR-patched.bin
  python3 patch_cables.py --udt Chimp-USBC-DT-1_14.bin Chimp-UDT-patched.bin

After patching:
  kblcrcfix <output.bin>          # fix CRC before flashing
  kblctl flash <output.bin>       # flash via kblctl (bootloader mode required)

Enter bootloader mode:
  SNR/Nova : press button in LED hole until LED flashes orange
  UDT      : use probeenterdfu (patch astrisprobed to recognize 0x168C first)
        """
    )
    ap.add_argument("input",  help="input firmware .bin")
    ap.add_argument("output", help="output patched .bin")

    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--snr", action="store_true",
                       help="patch SNR/Nova: PID 0x1624 -> 0x1621 (Kanzi)")
    group.add_argument("--udt", action="store_true",
                       help="patch UDT: is_UDT() always returns 0 (Chimp)")

    ap.add_argument("--skip-crc", action="store_true",
                    help="skip CRC fix (use if you have kblcrcfix externally)")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="auto-confirm all prompts")
    args = ap.parse_args()

    # Load
    with open(args.input, 'rb') as f:
        buf = bytearray(f.read())

    print(f"Input  : {args.input} ({len(buf):#x} bytes)")

    # Sanity check
    fw_len = struct.unpack_from('<I', buf, 0x401C)[0]
    print(f"FW len : {fw_len:#x} (starts at 0x4000, ends at {0x4000+fw_len:#x})")

    # Patch
    if args.snr:
        if args.yes:
            # Skip interactive confirm
            buf[SNR_PATCH_OFFSET]   = SNR_PATCH[0]
            buf[SNR_PATCH_OFFSET+1] = SNR_PATCH[1]
            print(f"\n[SNR] Patched MOVS R1, #0x24 -> MOVS R1, #0x21 @ {SNR_PATCH_OFFSET:#x}")
        else:
            if not patch_snr(buf):
                sys.exit(1)
    else:
        if args.yes:
            buf[UDT_FN_OFFSET:UDT_FN_OFFSET+4] = UDT_PATCH
            print(f"\n[UDT] Patched is_UDT() @ {UDT_FN_OFFSET:#x}: MOVS R0,#0; BX LR")
        else:
            if not patch_udt(buf):
                sys.exit(1)

    # CRC fix
    if not args.skip_crc:
        print(f"\n[CRC] Fixing CRC...")
        fix_val, final_crc = fix_crc(buf)
        print(f"  Fix value written : {fix_val:#010x}")
        print(f"  Final CRC         : {final_crc:#010x}")
        if final_crc == 0:
            print(f"  [OK] CRC is zero - bootloader will accept firmware")
        else:
            print(f"  [WARN] CRC is not zero ({final_crc:#010x})")
            print(f"  [WARN] Run kblcrcfix on the output before flashing!")
    else:
        print(f"\n[CRC] Skipped - run kblcrcfix before flashing!")

    # Write
    with open(args.output, 'wb') as f:
        f.write(buf)

    print(f"\nOutput : {args.output}")
    print("Done.")
    print()
    print("Next steps:")
    if args.snr:
        print("  1. Enter bootloader: press button in LED hole until LED flashes orange")
        print("  2. Flash: kblctl flash", args.output)
        print("  3. SNR should now enumerate as PID 0x1621 (Kanzi)")
    else:
        print("  1. Patch astrisprobed to recognize 0x168C, use probeenterdfu to enter bootloader")
        print("  2. Flash: kblctl flash", args.output)
        print("  3. UDT should now be recognized as Chimp by Astris")

if __name__ == "__main__":
    main()
