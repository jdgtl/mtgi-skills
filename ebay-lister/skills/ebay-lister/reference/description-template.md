# Listing description template (MTGI house style)

Every MTGI listing uses the same HTML body, taken from the sold listings
(Micron 5300 PRO 287403744539, LSI CacheVault 287316056397, ASRock SPC621D8
287316057086). Put it in the draft's `listingDescription`; keep `description`
as the plain-text version (it feeds `product.description`, 4000-char cap).

Sections, in order — drop a section only if there is nothing to say:

1. `h2` — `<Product name> — <MPN>` (yellow `#f5af02` underline)
2. `h3` — `Condition: <New (Open Box) | New (OEM Bulk) | …> — <one-phrase qualifier>`
3. `p` — bold lead sentence, then the honest condition story (what was opened,
   why, what remains sealed, tested or not, quantity available)
4. `hr`
5. `h3 Product Specifications` + two-column table, alternating `#f7f7f7` rows,
   label column 35%. Manufacturer and MPN first; UPC last if known.
6. `h3 What's Included (per unit|per kit)` + `ul`
7. `h3 Ideal Use Cases` + `ul` (3–5 bullets)
8. `hr`
9. `h3 Shipping & Returns` — handling time, service **in bold** with "(free
   shipping)", upgrade if any, "Ships from Manchester, MA.", packaging line,
   "30-day returns accepted."

## Skeleton

```html
<div style="font-family: Arial, sans-serif; max-width: 800px; color: #333; line-height: 1.5;">
<h2 style="border-bottom: 3px solid #f5af02; padding-bottom: 8px; margin-bottom: 16px;">PRODUCT &mdash; MPN</h2>
<h3 style="margin-top: 0;">Condition: New (Open Box) &mdash; QUALIFIER</h3>
<p><strong>LEAD.</strong> CONDITION STORY.</p>
<hr style="margin: 24px 0; border: none; border-top: 1px solid #ddd;">
<h3>Product Specifications</h3>
<table style="width: 100%; border-collapse: collapse;">
<tr style="background: #f7f7f7;"><td style="padding: 10px; border: 1px solid #e0e0e0; width: 35%;"><strong>Manufacturer</strong></td><td style="padding: 10px; border: 1px solid #e0e0e0;">…</td></tr>
<tr><td style="padding: 10px; border: 1px solid #e0e0e0;"><strong>Part Number (MPN)</strong></td><td style="padding: 10px; border: 1px solid #e0e0e0;">…</td></tr>
<!-- alternate the #f7f7f7 background on even rows -->
</table>
<h3 style="margin-top: 24px;">What&rsquo;s Included (per unit)</h3><ul><li>…</li></ul>
<h3 style="margin-top: 24px;">Ideal Use Cases</h3><ul><li>…</li></ul>
<hr style="margin: 24px 0; border: none; border-top: 1px solid #ddd;">
<h3>Shipping &amp; Returns</h3>
<p>Ships within 2 business days via <strong>USPS Ground Advantage (free shipping)</strong>; USPS Priority Mail upgrade available at checkout. Ships from Manchester, MA. Carefully packaged with anti-static protection. 30-day returns accepted.</p>
</div>
```

Worked example: `01_Clients/mtgi/work/ebay/drafts/MTGI-ET91000SM20.json` → `listingDescription`.
