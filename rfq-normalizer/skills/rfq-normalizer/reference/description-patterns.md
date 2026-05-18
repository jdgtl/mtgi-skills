# Description Patterns — Spec Extraction

Used by `scripts/split_description.py` to extract structured specs from free-text descriptions.

## Size (capacity)

Match the first occurrence. Always uppercase the unit.

| Pattern | Example | Output |
|---|---|---|
| `\d+(\.\d+)?\s*TB` | "1.6TB", "1.92 TB" | `1.6TB`, `1.92TB` |
| `\d+\s*GB` | "32GB", "480 GB" | `32GB`, `480GB` |
| `\d+\s*MB` | "512MB" | `512MB` |

Reject sizes < 1MB or > 1000TB (likely false matches).

## Interface

Case-insensitive contains-match.

| Pattern | Output (canonical) |
|---|---|
| `SAS`, `SAS-12`, `12Gb SAS`, `12G SAS` | `SAS` |
| `SATA`, `SATA-6`, `SATA III`, `SATA 3` | `SATA` |
| `NVMe`, `NVME` | `NVMe` |
| `PCIe Gen3`, `PCIe Gen4`, `PCIe Gen5` (capture gen) | `PCIe Gen4` |
| `PCIe x4`, `PCIe x8`, `PCIe x16` (capture lanes) | `PCIe x4` |
| `10GbE`, `25GbE`, `40GbE`, `100GbE` (NIC speeds) | `10GbE` |
| `FC`, `Fibre Channel`, `FibreChannel` | `FC` |

If multiple interface tokens appear (e.g. "PCIe Gen4 NVMe SSD"), join with space: `PCIe Gen4 NVMe`.

## Drive Type / Device Type

Match the first occurrence.

| Pattern | Output |
|---|---|
| `SSD`, `Solid State Drive` | `SSD` |
| `HDD`, `Hard Drive`, `Hard Disk` | `HDD` |
| `M.2` (when not paired with another type) | `M.2 SSD` |
| `U.2` | `U.2 SSD` |
| `NIC`, `Network Card`, `Network Adapter`, `Ethernet Adapter` | `NIC` |
| `Switch` (when context is networking) | `Switch` |
| `HBA`, `Host Bus Adapter` | `HBA` |
| `RAID Controller`, `RAID Card` | `RAID Controller` |
| `Memory`, `RAM`, `DIMM`, `RDIMM`, `LRDIMM` | `Memory` |
| `CPU`, `Processor` | `CPU` |
| `GPU`, `Graphics Card` | `GPU` |

If none match, leave blank and flag for enrichment.

## Form Factor

Match the first occurrence.

| Pattern | Output |
|---|---|
| `2.5"`, `2.5 inch`, `2.5in`, `SFF` | `2.5in` |
| `3.5"`, `3.5 inch`, `3.5in`, `LFF` | `3.5in` |
| `M.2 2280`, `2280` | `M.2 2280` |
| `M.2 2230`, `2230` | `M.2 2230` |
| `M.2 22110`, `22110` | `M.2 22110` |
| `Low Profile`, `LP`, `Half-Height` | `LP PCIe` |
| `Full Height`, `FH` | `FH PCIe` |
| `1U`, `2U` (rack equipment) | `1U`, `2U` |

## When to bail out

If the description is < 4 characters or contains only generic words ("Drive", "Module", "Part"), do not attempt extraction. Leave all four fields blank and flag for enrichment.

## Examples

| Input | Output |
|---|---|
| `1.6TB SATA SSD 2.5"` | size=`1.6TB`, interface=`SATA`, drive_type=`SSD`, form_factor=`2.5in` |
| `32GB DDR4-3200 RDIMM ECC` | size=`32GB`, interface=blank, drive_type=`Memory`, form_factor=blank |
| `480GB SATA Read-Intensive SSD` | size=`480GB`, interface=`SATA`, drive_type=`SSD`, form_factor=blank |
| `Intel X710-DA2 10GbE NIC` | size=blank, interface=`10GbE`, drive_type=`NIC`, form_factor=blank |
| `Cisco Nexus 48-port` | size=blank, interface=blank, drive_type=`Switch`, form_factor=blank |
