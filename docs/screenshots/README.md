# PRIMERS OS screenshots

Taken from the image itself, booted in a VM by the `brand` VM test
(`primers-distro/tests/vm/run_vm_tests.py brand`), which also checks what
they show; the release workflow keeps a fresh set with every run's VM test
results. Every logo in them is the official artwork from
`branding/primers-os-logo`, used as it is.

| File | What it shows |
|---|---|
| `boot-splash-cursor-on.png`, `boot-splash-cursor-off.png` | The boot splash: the white P on Night Ink #12161C, its green cursor blinking in steps (0.5 s on, 0.5 s off: a 1.0 s blink; the brand's 1.06 s doesn't fit Plymouth's fixed 2 s throbber cycle evenly) |
| `boot-splash-frames.png` | The splash's frames: cursor on, cursor off, and the still frame used with reduced motion (`sudo primers-reduce-motion on`) |
| `login-screen.png` | The login screen with Lab Mode on: the lockup above the sign-in box, the app icon as the account picture |
| `desktop.png` | The desktop with the PRIMERS Brain open: the app icon on its window and in the taskbar, window frames in the brand colours |
| `desktop-wallpaper.png` | The wallpaper |
| `exam-kiosk.png` | Exam Mode: the kiosk with a demo exam |
| `privacy-notice.png` | The privacy notice at an account's first sign-in on an installed PC: OK stays off until "I have read this privacy notice" is ticked (VM test `privacy`) |

Screen size 1280×800 (a VM's display; real PCs use their own resolution).
