# Rollback plan: returning the pilot PCs to their previous system

> **Draft for review.** Agree it with the lab's owner and IT before
> anything is installed.

PRIMERS OS is installed with **Erase disk**: the previous system (usually
Windows) is gone from the PC once the install starts. Rolling back means
putting back a copy made beforehand. **Without a tested backup there is
no rollback**, only a fresh install of the old system.

## Before the pilot (once per PC, before installing PRIMERS OS)

1. **Choose the backup tool and place.** A free disk-imaging tool that
   starts from USB, such as [Clonezilla Live](https://clonezilla.org/)
   ("device-image" mode), and an external USB disk or a network share big
   enough for every PC's used space. Label it "Pilot backups: do not
   erase".
2. **Write down, per PC:** the PC label, make and model, firmware settings
   that will change (boot order, USB boot, Secure Boot, firmware password),
   the Windows edition, and the **BitLocker recovery key** if the disk is
   encrypted (an encrypted disk must be backed up with its key, or not at
   all). A Windows licence tied to the PC (a "digital licence") normally
   reactivates by itself when the same edition is put back on the same PC;
   write down any product key on a sticker anyway.
3. **Back up the whole disk** of each PC to an image named after the PC
   label (e.g. `VU-CS1-07-2026-12-01`). Note the image name on the PC's
   install checklist.
4. **Test a restore before installing anything:** restore one PC's image to
   that PC (or one of each model) and check it starts, signs in and is
   activated. A backup that hasn't been restored once is not a backup.
5. Keep the backups until the pilot has ended and the university has
   decided; they hold the old system's data, so store them like any other
   staff data.

## When to roll back

The decision belongs to the lab's owner (head of department or IT lead),
with the Primers team informed. Reasons include: the university ends the
pilot; PCs are needed back with the old system for teaching or exams; a
problem that can't be fixed in the time available (hardware that doesn't
work, or the exam platform not working with PRIMERS OS).

**Partial rollback, no reinstall:** if only Exam Mode or Lab Mode is the
problem, they can be switched off on a PC without changing anything else:

```bash
sudo primers-exam stop        # ends Exam Mode and every lock
sudo primers-lab disable      # removes the shared lab account (and its files)
sudo primers-fleet leave      # this PC stops taking commands from the invigilator's PC
```

## Rolling back one PC (about 20–40 minutes)

1. **Keep the records first.** The exam logs on the PC are evidence and
   personal data: if they haven't been collected already, collect them
   (`sudo primers-fleet collect DIR` on the invigilator's PC, or
   `sudo primers-privacy export DIR` on the PC itself), and copy the
   `benchmark` reports. Store them as the privacy notice says.
2. **Firmware:** sign in to the firmware with the firmware password and turn
   **USB boot on** (needed to start the imaging tool).
3. Start the imaging tool from its USB stick and **restore the PC's image**
   to the internal disk ("restoredisk"). Check the image name matches the
   PC label.
4. Remove the stick and start the PC: the previous system must start and
   sign in. Check Windows is activated (Settings › Activation), and if
   BitLocker was on, that it is on again.
5. **Firmware back** to how it was written down in step 2 of "Before the
   pilot" (boot order, USB boot, Secure Boot). Remove the firmware password
   if the PC didn't have one before, or hand it to the lab's IT.
6. Note on the results sheet: date, who, "rolled back", any problem.

## If there is no backup

Reinstall the previous system from the PC maker's recovery media or the
vendor's installation media for the same edition, then the lab's usual
software. Licences: a digital licence normally reactivates on the same
hardware; otherwise use the product key written down before the pilot. This
takes much longer (hours per PC with software), which is why the backup and
the test restore come first.

## The invigilator's PC

If a staff PC was used as the invigilator's PC, either roll it back the
same way or, if it keeps PRIMERS OS, unpair the lab PCs from it:
`sudo primers-fleet forget NAME` for each lab PC.

## After the pilot

Delete the exam logs and exports when they are no longer needed (the
privacy notice's retention time is 90 days on the PCs); keep the
anonymous feedback and the results sheet for the pilot report.
