# Patches for Primers Store

Changes to `Jothankato05/primers-store` made from a session that could read
that repository but not push to it. Apply one in a clone of the store and
push it from there:

```bash
git am 0001-admin-approve-or-reject-app-versions.patch
```

| Patch | What it does |
|---|---|
| `0001-admin-approve-or-reject-app-versions.patch` | The admin page can approve or reject each app version (a version isn't offered for download until approved), shows how many versions of each app wait for review, and filters the app list to "Versions to review". With tests (`npm test`: 12 of 12). |

Remove a patch from here once it is in the store's `main`.
