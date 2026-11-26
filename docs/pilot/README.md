# Pilot kit: PRIMERS OS in one lab at Veritas University

> **Draft for review.** Nothing here is to be printed or used in the lab
> until the Primers team has approved it.

For a practice exam in one lab, with PRIMERS OS **v1.0.0-rc1** (a release
candidate: for pilots and practice exams, not yet for a real exam). The
full instructions are in the [pilot guide](../pilot-guide.md); this kit is
what people carry and fill in.

| File | Who uses it | When |
|---|---|---|
| [rollback-plan.md](rollback-plan.md) | Lab administrator | **Before anything is installed** (backups), and if the pilot has to stop |
| [install-checklist.html](install-checklist.html) ([PDF](install-checklist.pdf)) | Whoever installs each PC | One printed sheet per PC, filled in during the install |
| [results-sheet.csv](results-sheet.csv) | Lab administrator | One row per PC, typed in from the checklists |
| [invigilator-card.html](invigilator-card.html) ([PDF](invigilator-card.pdf)) | Invigilators | One A4 card at the invigilator's desk during the practice exam |
| [feedback-form.html](feedback-form.html) ([PDF](feedback-form.pdf)) | Students and invigilators | Right after the practice exam |

## Order

1. Back up every PC's current system and test one restore
   ([rollback-plan.md](rollback-plan.md), "Before the pilot").
2. Install each PC with the checklist; type each sheet into the results
   sheet.
3. Pair the lab with the invigilator's PC (pilot guide, "Run the whole lab
   from the invigilator's PC").
4. Run the practice exam with the invigilator card on the desk.
5. Hand out the feedback forms; collect the exam logs
   (`sudo primers-fleet collect`).
6. Send the results sheet, the benchmark reports and the feedback (no
   names) to Primers: they go into section 7.11 of the knowledge base.

## The results sheet's columns

| Column | What to write |
|---|---|
| `pc_id` | The label on the PC (e.g. `VU-CS1-07`) |
| `room`, `seat` | Where it stands |
| `make_model`, `cpu`, `ram_gb` | From the sticker or the `benchmark` output |
| `disk_type` | `HDD` or `SSD` (the `benchmark` output says) |
| `disk_gb` | Disk size, from `benchmark` |
| `firmware` | `BIOS` or `UEFI` |
| `secure_boot` | `on`, `off` or `n/a` (BIOS PCs) |
| `firmware_password_set`, `usb_boot_off` | `yes` / `no` |
| `primers_version` | `v1.0.0-rc1` |
| `installed_on`, `installed_by` | Date (YYYY-MM-DD) and initials |
| `lab_mode_on`, `fleet_paired` | `yes` / `no` |
| `stopwatch_power_on_to_login_s` | Seconds from pressing the power button to the login screen, with a stopwatch, after the PC was fully off |
| `benchmark_boot_to_login_s` | "Boot to login" from `benchmark` |
| `ram_in_use_idle_mb` | "RAM in use now" from `benchmark`, run after two idle minutes |
| `disk_used_gb` | "Disk used" from `benchmark` |
| `kiosk_test` | `pass` or `fail` (the kiosk test on the checklist) |
| `kiosk_test_notes`, `problems` | Anything that went wrong, in a few words; seat numbers, times |
| `checked_by` | Initials of the person who checked the sheet |

The sheet holds hardware facts only: no student names or matric numbers.

## Printing

The HTML files print on A4 from any browser (File › Print, "A4", margins
"Default", headers and footers off). The PDFs next to them are the same
pages, made with `node docs/pilot/make-pdfs.js` (needs Node and Playwright
with Chromium), which also checks each fits its pages.
