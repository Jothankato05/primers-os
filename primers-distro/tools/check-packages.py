#!/usr/bin/env python3
"""
Verify that every package PRIMERS OS installs exists in the Ubuntu archive.

Checks config/packages-lists/*.list.chroot and the module registry against
the jammy (+updates) package indexes for amd64 and i386, so a typo or a
Debian-only package name fails in seconds instead of 30 minutes into an
ISO build.

  tools/check-packages.py [--suite jammy] [--mirror URL]
"""

import argparse
import gzip
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DISTRO = os.path.dirname(HERE)
COMPONENTS = ["main", "restricted", "universe", "multiverse"]


def fetch_index(mirror, suite, component, arch):
    url = f"{mirror}/dists/{suite}/{component}/binary-{arch}/Packages.gz"
    with urllib.request.urlopen(url, timeout=120) as r:
        data = gzip.decompress(r.read()).decode("utf-8", "replace")
    names = set()
    for line in data.splitlines():
        if line.startswith("Package: "):
            names.add(line[9:].strip())
        elif line.startswith("Provides: "):
            for item in line[10:].split(","):
                names.add(item.strip().split(" ")[0])
    return names


def read_list(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            pkg = line.split("#", 1)[0].strip()
            if pkg:
                yield pkg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="jammy")
    ap.add_argument("--mirror", default="http://archive.ubuntu.com/ubuntu")
    args = ap.parse_args()

    available = {"amd64": set(), "i386": set()}
    for arch in available:
        for suite in (args.suite, f"{args.suite}-updates"):
            for comp in COMPONENTS:
                available[arch] |= fetch_index(args.mirror, suite, comp, arch)
    # Firefox comes from Mozilla's repository (see build.sh)
    available["amd64"].add("firefox")

    wanted = []
    lists_dir = os.path.join(DISTRO, "config", "packages-lists")
    for name in sorted(os.listdir(lists_dir)):
        if name.endswith(".list.chroot"):
            wanted += [(f"packages-lists/{name}", p) for p in read_list(os.path.join(lists_dir, name))]

    registry = os.path.join(DISTRO, "overlays", "usr", "lib", "primers", "modules", "module_registry.json")
    with open(registry, encoding="utf-8") as f:
        for mod in json.load(f)["modules"]:
            wanted += [(f"module '{mod['name']}'", p) for p in mod.get("packages", [])]

    conf = {}
    with open(os.path.join(DISTRO, "config", "build.conf"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("KERNEL_PACKAGE="):
                conf["kernel"] = line.split(":-", 1)[1].split("}", 1)[0]
    if conf.get("kernel"):
        wanted.append(("build.conf KERNEL_PACKAGE", conf["kernel"]))
    wanted.append(("build.sh", "casper"))

    missing = []
    for source, pkg in wanted:
        name, _, arch = pkg.partition(":")
        arch = arch or "amd64"
        if name not in available.get(arch, set()):
            missing.append(f"{source}: {pkg}")

    print(f"Checked {len(wanted)} package references against Ubuntu {args.suite}.")
    if missing:
        print("Missing packages:")
        for m in missing:
            print(f"  ✗ {m}")
        return 1
    print("All packages exist. ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
