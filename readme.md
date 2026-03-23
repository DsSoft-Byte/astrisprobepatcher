# astrisprobepatcher

Firmware patcher for Apple retail technician cables to make them recognized by Astris as real debug probes.

| Cable | Real probe | PID before | PID after |
|-------|-----------|------------|-----------|
| SNR / Nova (Lightning) | Kanzi | 0x1624 | 0x1621 |
| UDT (USB-C) | Chimp | 0x168C | 0x162C |

## Requirements

- Python 3.6+
- `kblcrcfix` from [kanzitools](https://github.com/nickmass/kanzitools) (required after patching)

## Usage

```bash
# Patch SNR/Nova -> Kanzi
python3 patch_cables.py --snr Kanzi-SNR-1_07.bin Kanzi-SNR-patched.bin

# Patch UDT -> Chimp
python3 patch_cables.py --udt Chimp-USBC-DT-1_14.bin Chimp-UDT-patched.bin

# Fix CRC before flashing (required)
kblcrcfix Kanzi-SNR-patched.bin
kblcrcfix Chimp-UDT-patched.bin
```

## Flashing

**SNR/Nova** — press the button in the LED hole with a SIM ejector until the LED flashes orange (bootloader mode), then:
```bash
kblctl flash Kanzi-SNR-patched.bin
```

**UDT** — no button hole, so enter bootloader via `probeenterdfu` (requires briefly patching `astrisprobed` to recognize `0x168C`), then flash and revert `astrisprobed`.

## What it patches

**SNR:** Single byte change — `MOVS R1, #0x24` → `MOVS R1, #0x21` at the USB PID assignment. Changes the reported PID from Nova to Kanzi.

**UDT:** Patches `is_UDT()` to always return 0 by replacing its prologue with `MOVS R0, #0; BX LR`. The function is called in multiple places so patching the function itself (rather than each call site) is the correct approach.

## Notes

- Confirmed on SNR v1.07 and UDT v1.14
- CRC fix is built into the script but the STM32 hardware CRC algorithm requires `kblcrcfix` for a correct result — always run it before flashing
- If you brick the SNR the bootloader (KanziBoot) is hard to kill — you can always re-enter bootloader mode and reflash
- If you brick the UDT the button is hidden under the bottom piece of the enclosure — it's reachable without major damage
