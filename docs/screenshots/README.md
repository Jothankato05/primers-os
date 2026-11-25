# PRIMERS OS screenshots

Taken from the image itself, booted in a VM by the `brand` VM test
(`primers-distro/tests/vm/run_vm_tests.py brand`), which also checks what
they show; the release workflow keeps a fresh set with every run's VM test
results. Every logo in them is the official artwork from
`branding/primers-os-logo`, used as it is.

| File | What it shows |
|---|---|
| `boot-splash-cursor-on.png`, `boot-splash-cursor-off.png` | The boot splash: the white P on Night Ink #12161C, its green cursor blinking in steps (1.06 s: on, then off) |
| `boot-splash-frames.png` | The splash's frames: cursor on, cursor off, and the still frame used with reduced motion (`sudo primers-reduce-motion on`) |
| `login-screen.png` | The login screen with Lab Mode on: the lockup above the sign-in box, the app icon as the account picture |
| `desktop.png` | The desktop with the PRIMERS Brain open: the app icon on its window and in the taskbar, window frames in the brand colours |
| `desktop-wallpaper.png` | The wallpaper |
| `exam-kiosk.png` | Exam Mode: the kiosk with a demo exam |

Screen size 1280×800 (a VM's display; real PCs use their own resolution).
