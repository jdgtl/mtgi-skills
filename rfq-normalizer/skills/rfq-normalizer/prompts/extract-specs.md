# LLM Fallback Prompt — Spec Extraction

Use this prompt only when `scripts/split_description.py` returns blank values for required fields AND no enrichment tier returned a high-confidence answer.

## Hard rule

**Never invent values.** If the description doesn't clearly state a value, return `null` for that field. The user will fill it in manually.

## Prompt

```
You are extracting structured specs from an IT equipment description for inventory cataloging.

Description: "{description}"

Extract these fields. Return null if not explicitly stated in the description.

- size           — storage capacity (e.g. "1.6TB", "32GB", "480GB"). null if not a storage device.
- interface      — bus interface (e.g. "SATA", "SAS", "NVMe", "PCIe Gen4", "10GbE"). null if unclear.
- drive_type     — device category (e.g. "SSD", "HDD", "NIC", "Memory", "CPU", "Switch"). null if unclear.
- form_factor    — physical size (e.g. "2.5in", "3.5in", "M.2 2280", "LP PCIe"). null if unclear.

Return JSON only, no prose:
{
  "size": "...",
  "interface": "...",
  "drive_type": "...",
  "form_factor": "...",
  "confidence": 0.0
}

Confidence: 0.95 if the description explicitly states every field. 0.5 if you're inferring from context. 0.0 if you had to guess.
```

## After extraction

If confidence < 0.9, surface to the user before accepting:

> I extracted these from the description but I'm not certain:
> - Size: 1.6TB
> - Interface: SATA
> - Drive type: SSD
> - Form factor: (couldn't determine)
> 
> Accept these, edit, or skip enrichment for this row?
