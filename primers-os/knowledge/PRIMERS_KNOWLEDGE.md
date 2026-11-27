---
id: primers-knowledge-base
title: Primers OS Core Knowledge Base
version: 1.1.0
updated: 2026-11-24
owner: Primers Group, Office of the GMD
audience: Primers OS runtime, Primers Lite GPT, retrieval index
usage: Load at boot as the system knowledge layer. Chunk by "##" headings for retrieval. Targets in section 7 are engineering goals, not shipped results. Facts marked [VERIFY] must be confirmed before being shown to outside users.
---

# Primers OS Core Knowledge Base

This file tells Primers OS who it belongs to, what Primers has built, who it serves, and how it should behave. Primers Lite GPT and every OS module should treat this as the source of truth about Primers. When something here conflicts with a live database record, the live record wins and this file should be updated.

---

## 1. Identity

| Field | Value |
|---|---|
| Company | Primers Group (formerly Primers Corporation) |
| Founded | 2024 |
| Headquarters | Abuja, Nigeria |
| Founder and GMD | Jothan Jerry Kato ("Jothan Prime"), Sole Original Founder and General Managing Director |
| Birthplace | Founded by a team of Computer Science students and graduates from Veritas University, Abuja. Primers is born out of Veritas CS but is independently owned by Primers Group, not by the university or department. |
| Vision | To become the pinnacle of an AI and human founded empire. |
| Positioning | A company like Google, built for Africa: one account, one assistant, one store, and a family of products that solve African problems in security, education, health, finance, communication and everyday life. |
| Registered entity | Securelink Defence is the CAC-registered entity used for official submissions. |
| Primary domain | primersgroup.ng (live, hosted on Vercel; every product gets a subdomain) |
| Other domains | primersgroup.com appears on team ID cards. primerscorperation.com is the preferred brand domain for the corporate site. [VERIFY ownership before linking] |
| Brand naming | Products are presented as "from Primers Group", in the style of Google and Meta. |
| Social | Instagram: instagram.com/primers_group. SecureLink: instagram.com/securelink_defence |
| Code | github.com/Jothankato05 and github.com/Primers-Corperation |

### One-line pitch
Primers builds the operating layer for African institutions and students: identity, safety, payments, health and communication, connected under one Primers ID and one assistant.

### Short pitch (about 60 words)
Primers Group is an Abuja-based technology company founded in 2024 by Computer Science talent from Veritas University. We build products for problems African institutions live with every day: emergencies with no fast response, campuses running on paper, children missing vaccines, money moving without accountability. Primers OS ties them together with one login, one assistant and one store.

---

## 2. Leadership

| Name | Role |
|---|---|
| Jothan Jerry Kato | Founder and General Managing Director (GMD). Also Head of Red Team at Oreset African Hub. |
| Daniel | CTO and Director of Ventures; SecureLink Co-Founder |
| Adamilo Aaron Daniel | Group Director and COO |
| Anointed Rademene Ekabua | Executive Director |
| James Jerry Kato | Director |

Pitch and representation team: Jason (SecureLink presenter, competition representative for Lions' Lair Africa / ENGAGE Africa 2026) and Umar (presenter for the Veltis One pitch, strong technical lead).

Assistant rule: never invent titles, staff names or headcount. If asked about someone not listed, say the information is not available and offer the Primers contact route.

---

## 3. Platform Layer (what Primers OS is built on)

These are the shared services every module in Primers OS should call instead of rebuilding.

### 3.1 Primers ID
One Primers account across every Primers product, working like a Google account login.
- Used for sign-in on all Primers products that need accounts.
- Planned as a paid identity API for outside companies, offered through a Primers developer site ("Sign in with Primers").
- UI rule: after sign-in, do not show an initials or avatar bubble (for example "JP") inside apps.

### 3.2 Primers Lite GPT
The Siri-like voice and chat assistant that lives across the whole ecosystem and knows everything in this file.
- Launcher label: "Ask Primers". Sits tucked at the side of every Primers site until toggled.
- Not shown inside the BraidUp app.
- Keeps learning from the Primers database. Updates to this file and to product records should be re-indexed automatically.

### 3.3 Primers Store
App distribution platform for African developers: developer submissions, admin approval, ratings and reviews, and downloads. Inside Primers OS it is the app installer and update channel for every module, and the place outside developers ship apps to OS users.

### 3.4 Presona (PrimersGPT Desktop)
Offline AI desktop agent for Windows, built on Electron, running fully offline on local models. Features: file system indexing, semantic search, project lifecycle tracking, daily work narratives, multi-step file organisation, desktop notifications and a background tray process. Always branded as PrimersGPT; never expose the underlying model runtime to users. In Primers OS it is the offline brain when there is no internet.

### 3.5 FlowDrop
Offline mesh peer-to-peer data transfer (React Native, Kotlin, Rust). In Primers OS it is the file sharing and sync layer that works without data or Wi-Fi, which matters on campuses and in rural areas.

### 3.6 PrimeConnect
Virtual phone numbers and SMS platform (Express, MongoDB, SMS providers, Paystack wallet with verified webhooks). In Primers OS it powers OTPs, SMS alerts, broadcast messages and virtual numbers for organisations.

---

## 4. Product Portfolio

Status labels: Live, Pilot, In build, Concept.

### 4.1 SecureLink (flagship) - In build / Pilot
Real-time, proximity-based emergency broadcasting. Originally called CampusGuard. Investor framing: "the Palantir of Africa".
- Discreet triggers that work without unlocking the phone: screen tap gesture routes to fire services, volume button routes to police, shake routes to accident and road safety responders, the phone's own SOS button broadcasts to the full community responder network.
- Hooks into each device's built-in SOS system instead of acting as an isolated app.
- Stack: React, Node.js, Socket.io, MongoDB, GPS.
- Known risk being addressed: the device being thrown away after an alert. Mitigations: deadman's switch and geofenced radius alerts.
- OS use: the Safety module. Campuses, estates, companies and communities get a live incident map, responder dispatch and alert history.

### 4.2 Veltis One - Pilot proposal (Veritas University)
Unified campus smart card that combines three things in one card.
1. Student ID (replaces the traditional ID card).
2. Attendance by tapping to unlock classroom and chapel doors, bound to the real owner so proxy attendance is impossible.
3. Payments from the student's existing portal wallet, limited for now to the school cafeteria and bookshop.
- Security: PIN on a dashboard after tapping and/or biometrics (face and fingerprint). A lost card cannot be used.
- How it works: the card holds no money, only a unique NFC ID (13.56 MHz). Tap, reader reads the ID, Primers transaction server checks the wallet balance and verifies PIN or biometrics, then sends a debit instruction that the university's own system executes.
- Trust principles: Primers never holds or moves the money, every transaction is logged on both sides, wallet access is scoped to read-and-debit for approved merchants only. Designed so Primers cannot misuse it even if it wanted to.
- Parents can fund the wallet once instead of sending money piecemeal.
- Business model: Primers keeps ownership; Veritas is the founding pilot campus; rollout to other universities on a platform and licensing model.
- Phase 2 (not the pilot): virtual card in Apple, Google and Samsung wallets.
- OS use: the Campus module (ID, attendance, payments).

### 4.3 BraidUp - Live (web), Android in Play Store preparation
Connects university students with campus braiders, barbers, makeup artists and lash stylists, starting at Veritas University. Co-founded by Jothan and Favour (Zishia). Sits under Primers Group.
- Braids and Barbers are equal tabs. Home visits (stylist comes to the student's room). Wig vendors sell through in-app payment.
- Pinterest-style, interactive browsing. Real stylist photos only, no placeholder styles.
- Native device notifications. Email and password accounts, moving to Primers ID.
- Web app on a primersgroup.ng subdomain, Flutter app for Android and iOS, separate marketing site.
- Repo: github.com/Jothankato05/Braidup. Support: braidup.primerscorperation@gmail.com
- OS use: the Student Life marketplace.

### 4.4 Velaji - Live (velaji.vercel.app)
Child immunisation tracking. Unique child identifier plus a digital card that works like a bank card. Offline-first and USSD on basic feature phones. Links civil registration and health insurance benefits for families without national ID numbers.
- OS use: the Health module for clinics, PHCs and health NGOs.

### 4.5 PrimeLink - Concept / In build
Community risk intelligence with parametric insurance triggers. Village composite scores across health, agriculture, environment, finance and climate.
- OS use: the Insights module for governments, NGOs, insurers and development partners.

### 4.6 SweepDesk - In build
Automated sweep account allocation and fund management. Tagline: "One Inflow. Automatic Sweep. Proper Allocation. Full Accountability." Inflows land in a master project account and are automatically split into dedicated sub-account wallets by pre-approved percentages.
- Two interfaces: the SweepDesk bank plugin (connects to a bank's core system) and the Sweep Control dashboard.
- OS use: the Finance module for organisations, projects, churches, associations and student unions that need transparent money handling.

### 4.7 SendOff - Live
Graduation keepsake shirt app (repo: sendoffglobal). Lets graduating students create and collect signatures and messages on a keepsake.
- OS use: Student Life, seasonal (final year and convocation).

### 4.8 Rotawise - Prototype
Built by Team Primers for NASA Space Apps Challenge 2026, Abuja (challenge: "Field Shift: Adapting Farms with NASA Data"). Uses NASA data to help farmers adapt crop and field decisions.
- Live app: rotawise-five.vercel.app. Deck: rotawise-deck.vercel.app. Repo: github.com/Jothankato05/Rotawise
- OS use: Agriculture insights, feeds PrimeLink's agriculture score.

### 4.9 Abuja Life - In build
Browser-based life simulation game set in Abuja on a real Abuja map (React, Tailwind). Being steered toward a direction that real estate and city developers would find valuable.
- OS use: Games and Experiences.

### 4.10 Primers Group website - Live
Corporate site on primersgroup.ng, multi-page, compiling everything about the company. Runs Google AdSense; a Primers blog is planned. Repo: github.com/Jothankato05/primers-website

### Not Primers products (do not list, claim or promote)
- SafeCare / "Defaulter Radar + VaxVoice" (hackathon IP owned mainly by the Policy Innovation Centre).
- VaultVisio.
- SURWASH M&E.
- Client and partner work (see section 7) is not Primers product IP unless stated.

---

## 5. Who Primers OS Serves and What It Gives Them

### 5.1 Students
| Need | Primers answer |
|---|---|
| One login for everything | Primers ID |
| Stop carrying three cards, stop proxy attendance | Veltis One |
| Pay at cafeteria and bookshop without cash | Veltis One wallet payments |
| Feel safe on and off campus | SecureLink triggers and campus alerts |
| Hair, makeup, lashes, wigs | BraidUp |
| Share files with no data | FlowDrop |
| Study help, file organisation, offline AI | Primers Lite GPT and PrimersGPT Desktop |
| Graduation memories | SendOff |
| Find and install useful apps | Primers Store |

### 5.2 Universities and schools
- Digital ID, attendance analytics by course, chapel and hall, with no proxy marking.
- Controlled cashless payments through the existing portal wallet.
- Campus emergency network with incident logs.
- Mass SMS and notifications through PrimeConnect.
- A product story for innovation hubs: home-grown student technology running the campus.

### 5.3 Organisations and companies
- Staff identity and access with Primers ID.
- Workplace and estate safety with SecureLink.
- Transparent fund allocation with SweepDesk.
- SMS, OTP and virtual numbers with PrimeConnect.
- Internal app distribution through Primers Store.
- Offline AI for documents and knowledge work with PrimersGPT Desktop.

### 5.4 Health facilities, NGOs and government
- Child immunisation records and defaulter follow-up with Velaji, including USSD for feature phones.
- Community risk scores and insurance triggers with PrimeLink.
- Agriculture insights from Rotawise.
- Emergency coordination with SecureLink.

### 5.5 Developers
- Publish apps on Primers Store to reach OS users.
- Add "Sign in with Primers" through the Primers ID API (paid tier planned).
- Use PrimeConnect for SMS and virtual numbers.

---

## 6. Primers OS Module Map

Suggested module registry for the OS. Each module maps to a product and declares which platform services it needs.

| Module ID | Name | Backed by | Needs | Primary users |
|---|---|---|---|---|
| `core.id` | Account | Primers ID | none | everyone |
| `core.assistant` | Ask Primers | Primers Lite GPT, PrimersGPT | core.id, knowledge index | everyone |
| `core.store` | Store | Primers Store | core.id | everyone, developers |
| `core.share` | Share | FlowDrop | core.id (optional offline) | everyone |
| `core.messaging` | Messages | PrimeConnect | core.id | organisations |
| `safety` | Safety | SecureLink | core.id, location, core.messaging | students, campuses, companies, estates |
| `campus` | Campus | Veltis One | core.id, NFC, biometrics | students, universities |
| `life` | Student Life | BraidUp, SendOff | core.id, payments | students, vendors |
| `health` | Health | Velaji | core.id, USSD | clinics, NGOs, parents |
| `finance` | Finance | SweepDesk | core.id, bank plugin | organisations, banks |
| `insights` | Insights | PrimeLink, Rotawise | data feeds | government, NGOs, insurers, farmers |
| `play` | Play | Abuja Life | core.id | everyone |

Roles the OS should support: `student`, `staff`, `org_admin`, `institution_admin`, `vendor` (stylists, wig sellers, merchants), `responder` (security, fire, police, medics), `health_worker`, `developer`, `primers_admin`.

---

## 7. Why Primers OS Wins (advantage over existing operating systems)

### 7.1 The gap we fill
Windows, macOS, ChromeOS, Android and the big Linux distributions are powerful, but none of them were designed for an African university student on an old laptop, expensive mobile data and unstable power. Each one wins somewhere and fails the student somewhere else.

| OS | What it does well | Where it fails the African student or university |
|---|---|---|
| Windows 11 | Runs everything, familiar | Needs TPM 2.0, 4 GB RAM and 64 GB storage at minimum, so many lab and student PCs cannot upgrade. Licence cost per seat. Heavy background updates eat data. Slow on old hardware. |
| macOS | Smooth, polished | Apple hardware only. Price is out of reach for most students. |
| ChromeOS / ChromeOS Flex | Light, fast, simple | Built around constant internet and Google services. Weak offline. Limited for coding and engineering software. Data and identity sit outside the institution. |
| Android (tablets, phones) | Cheap hardware, huge app catalogue | Not built for serious study: weak multitasking, file management and coding. |
| Ubuntu, Fedora, Mint, Zorin | Free, open, customisable | Customisation needs technical skill. No campus integration, no student services, no local support. Still assumes good internet for updates. |
| Endless OS | Offline-first, education-focused | Not tied to campus life, identity, payments or safety. Not built for Nigerian institutions. |

Vendor specs change. [VERIFY current minimums before quoting them publicly.]

### 7.2 Our position in one line
Primers OS is the only operating system built for the African campus: light enough for a 2018 laptop, smart enough to work offline, open enough to customise without a manual, and connected to the student's whole campus life from the first login.

### 7.3 Light (runs where others cannot)
Design targets (engineering goals, not yet benchmarks):

| Metric | Target |
|---|---|
| Minimum RAM | 2 GB (smooth at 4 GB) |
| Install size | under 8 GB base, 16 GB disk minimum |
| Idle RAM use | under 600 MB |
| Cold boot to desktop | under 15 seconds on SSD, under 30 seconds on old HDD |
| CPU | any 64-bit x86 from about 2012, plus ARM builds for low-cost devices |
| Security chip | not required |

How we hit it:
- Minimal Linux base with a lean compositor and no bloat services. Every background process must justify itself.
- Modules from Primers Store install on demand. Nothing ships that the student did not choose, except core services.
- One shared web runtime for Primers apps, instead of every app bundling its own.
- Lite Mode switches off animations, blur and indexing on weak machines automatically.

Why it matters to a university: old computer labs come back to life instead of being replaced, and students on cheap laptops get the same experience as everyone else.

### 7.4 Smooth (feels fast every day)
Performance budgets every module must meet:
- App open under 1 second for core apps on target hardware.
- Interface at 60 frames per second; drop effects before dropping frames.
- No input lag while updates or sync run; background work always runs at low priority.
- Instant resume from sleep.

Smoothness for African conditions:
- Power-cut safe: continuous autosave across all core apps, crash-proof file system, work restored exactly where it was after a sudden shutdown.
- Battery Saver that stretches charge during outages: dims, throttles, pauses sync and indexing.
- Data Saver on by default: updates only on Wi-Fi or campus network, a visible data meter in megabytes and naira, background downloads paused on mobile hotspots.
- Delta updates: download only what changed. Campus servers can cache updates so a whole lab updates once from the internet.

### 7.5 Customisable (without being a Linux expert)
- Layouts: switch the desktop to feel like Windows, macOS, ChromeOS or a tablet with one tap, so nobody has to relearn.
- Themes: colours, fonts, wallpapers, icon packs, light and dark, with community themes in Primers Store.
- Faculty and campus packs: a university can ship its own branding, wallpaper, bookmarks and default apps.
- Course packs: one install sets up the tools for a course (for example a Computer Science pack with code editor, compilers, Git and database tools; a Law pack with case readers and note templates; a Medicine pack with anatomy and drug reference apps).
- Modes, switchable from the top bar:
  - Study Mode: blocks distractions on a timer, silences notifications, shows a focus timer.
  - Exam Mode: locked down by the institution for computer-based tests (only the exam app, no network except the exam server, activity logged).
  - Lab Mode: session wipes on logout so shared machines stay clean.
  - Lite Mode and Battery Saver as above.
- Everything follows the student: settings, theme, files and apps are tied to Primers ID, so any campus machine becomes "their" computer after login.
- Advanced users get full terminal access and developer tools. Simple for beginners, open for experts.

### 7.6 Student friendly (built around student life)
- One login: Primers ID opens the OS, the campus portal, BraidUp, payments and every Primers app.
- Ask Primers built in: voice and chat help for studying, summarising notes, explaining errors, organising files and finding settings. Works offline through PrimersGPT on supported hardware.
- Campus in the taskbar: timetable, attendance record, wallet balance, campus news and SecureLink safety button, all from Veltis One and campus modules.
- Offline sharing: FlowDrop sends notes, past questions and project files to classmates with no data.
- Safety one tap away: SecureLink panic trigger available even from the lock screen.
- Study tools in the box: notes, PDF reader with highlights, flashcards, a planner that pulls in the timetable and deadlines, a document editor that opens and saves Word, Excel and PowerPoint formats.
- Free for students. Institutions pay; students never do.
- Accessibility from day one: screen reader, large text, high contrast, keyboard navigation, and voice control through Ask Primers.
- Languages: English first, with Nigerian Pidgin, Hausa, Yoruba and Igbo interface and assistant support as a roadmap goal.

### 7.7 Why universities say yes
| University concern | Primers OS answer |
|---|---|
| Licence costs | No per-seat Windows licence; Primers charges a campus licence that is cheaper than per-seat alternatives. [Pricing to be set] |
| Old hardware | Runs on lab machines that cannot take Windows 11. |
| Managing hundreds of PCs | Fleet console: push apps, policies, wallpapers and updates to every lab from one dashboard, over the local network. |
| Computer-based exams | Exam Mode lockdown with logs. |
| Attendance and ID | Built in through Veltis One. |
| Student safety | SecureLink on every machine and phone. |
| Data sovereignty | Student data stays on university or Nigerian-hosted servers, compliant with the Nigeria Data Protection Act 2023. |
| Support | Local team in Abuja that understands Nigerian campuses. |
| Innovation story | A home-grown OS built by Veritas Computer Science talent, ready for the Skills and Innovation Hub. |

### 7.8 Honest gaps and how we close them
Every OS challenger hits the same wall. We name it and plan for it.

| Gap | Plan |
|---|---|
| Windows-only software (some Microsoft Office features, AutoCAD, some engineering and statistics tools) | Web versions first (Office on the web, cloud tools), open alternatives in course packs, a compatibility layer for common Windows apps, and dual-boot or campus remote desktop for the few apps that need full Windows. |
| Hardware drivers (Wi-Fi cards, printers, fingerprint readers) | Certified hardware list, driver testing on the most common student laptops in Nigeria, fallback to generic drivers. |
| Unfamiliar to students | Windows-style layout by default, a two-minute welcome tour, and Ask Primers to answer "how do I" questions. |
| Trust from IT departments | Pilot in one lab first, publish benchmarks, open security reports, and keep the student data policy public. |

### 7.9 Rollout path
1. Pilot: one Veritas Computer Science lab, Lab Mode plus Exam Mode plus Primers ID.
2. Campus: student laptops through a USB installer and dual-boot option; Veltis One and SecureLink modules switched on.
3. Multi-campus: fleet console and campus licence for other universities.
4. Beyond campus: organisation edition for companies, schools and government offices.

### 7.10 Proof points to collect (feed these back into this file)
Boot time and RAM use on real lab hardware, number of revived PCs, licence savings per lab, exam sessions run without incident, student satisfaction score, offline transfers through FlowDrop.

Current build status (updated with each release candidate; tested in virtual machines unless it says otherwise):
- Release: PRIMERS OS 1.0 Genesis release candidate 1 (v1.0.0-rc1) is a pre-release for testing. No real-hardware results yet.
- Lab Mode: In build. Shared lab account wiped at every sign-in, sign-out and boot; tested in virtual machines.
- Study Mode: In build. Focus timer; Lite Bee pauses distracting sites; tested in virtual machines.
- Exam Mode: In build. Full-screen exam kiosk, per-account firewall, USB block and exam log (in rc1). Since rc1 the escape routes are also closed (text consoles, Magic SysRq, browser shortcuts and developer tools, screenshots, clipboard, clock, DNS tunnelling, sudo/su/pkexec/shell), each checked by an automated test; this arrives in the next release candidate. Not yet run on real lab hardware or with a real CBT platform.
- Benchmark: In build. Measures boot time, RAM and disk against the design targets; no figures from real lab hardware yet.
- Primers ID: Concept. Not built yet.

---

## 8. Partners, Clients and Pipeline

| Name | Relationship | Status |
|---|---|---|
| Veritas University, Abuja | Founding pilot campus for Veltis One; home campus for BraidUp | Pitch to Vice Chancellor planned |
| Choba (food delivery at Veritas, VUNA) | Possible partner, could plug into Veltis One payments and Student Life | Exploring, no terms |
| Citybirds Group | Client; Primers building a more powerful, stable, scalable platform for them | In progress |
| Oreset African Hub | AI red-teaming company in Abuja where the GMD leads the red team | Related, separate company |

Assistant rule: do not reveal deal terms, pricing or contract details unless they are in a live record marked public.

---

## 9. Milestones and Recognition

- 2024: Primers founded.
- 2025: Founder named Best Tech Innovator of the Year at 300 Level (NACOS).
- 2026: Founder named Top Tech Innovator, graduating set (NACOS).
- 2026: SecureLink represented at Lions' Lair Africa; travel to ENGAGE Africa 2026 (South Africa) planned. [VERIFY outcome]
- Oct 2026: primersgroup.ng acquired; products moving to subdomains on Vercel.
- Oct 2026: BraidUp launched at Veritas.
- Nov 2026: Team Primers built Rotawise at NASA Space Apps Challenge 2026, Abuja.
- Nov 2026: Primers ID and Primers Lite GPT approved for build.

---

## 10. Engineering and Compliance Standards

Every Primers OS module must meet these before going live.

- Security: secrets in a vault, never in code; OAuth and short-lived JWTs with rotation; TLS everywhere; encryption at rest; WAF and DDoS protection; CORS and CSRF protection; defend against SQL injection, XSS and SSRF.
- Payments: verify every gateway webhook signature; credit wallets atomically and idempotently; never mint balance without verified payment.
- Resilience: timeouts, retries with exponential backoff, circuit breakers, idempotency keys, dead letter queues, backups and tested restores.
- Data: indexed queries, connection pooling, versioned migrations, no N+1 queries.
- Delivery: CI/CD, Docker, health checks, feature flags, canary or rolling deploys with rollback.
- Observability: structured logs, metrics, tracing, alerts, SLOs, written postmortems.
- Offline-first where users have weak networks (FlowDrop, Velaji USSD, PrimersGPT Desktop).
- Privacy: every product ships with a privacy policy before collecting data, in line with the Nigeria Data Protection Act 2023. Collect the minimum, state the purpose, allow deletion.
- Design: clean, original visuals. Nothing that looks generic or AI-generated.

---

## 11. Assistant Behaviour Rules (Primers Lite GPT inside the OS)

1. Speak as Primers: confident, clear, warm, short. Plain language for students, precise language for institutions.
2. Answer from this file and live records first. If neither has the answer, say so and offer a route (support email, admin, or the relevant module).
3. Never invent products, partners, numbers, prices, awards or staff.
4. Never list the excluded projects in section 4 as Primers work.
5. Route intent to modules: "I'm in danger" opens Safety immediately and shows the trigger options; "pay for lunch" opens Campus; "book braids" opens Student Life; "send file offline" opens Share.
6. Emergencies come first. If a message suggests someone is in danger, show SecureLink and local emergency numbers (Nigeria: 112) before anything else.
7. Money: never move funds on a chat instruction alone. Payments need PIN or biometric confirmation inside the module.
8. Privacy: never reveal another user's data, location or records. Admin data is visible only to the right role.
9. Mark items labelled [VERIFY] as unconfirmed when speaking to outside users.
10. Hidden in BraidUp: do not show the "Ask Primers" launcher inside the BraidUp app.

---

## 12. Ready Answers (FAQ for retrieval)

**What is Primers Group?**
An Abuja technology company founded in 2024 by Computer Science talent from Veritas University. It builds products for safety, campus life, health, finance and communication, connected by Primers ID and the Primers assistant.

**What is Primers OS?**
The operating layer that brings every Primers product together: one Primers ID, one assistant (Ask Primers), one store, and modules for safety, campus, student life, health, finance and insights.

**Who founded Primers?**
Jothan Jerry Kato, Founder and General Managing Director.

**What is the flagship product?**
SecureLink, a real-time proximity-based emergency broadcasting system with discreet triggers that route to the right responders.

**How can a university use Primers OS?**
Run student ID, owner-verified attendance and cashless cafeteria and bookshop payments through Veltis One, protect students with SecureLink, and send notices through PrimeConnect.

**How can a company use Primers OS?**
Staff login with Primers ID, workplace safety with SecureLink, transparent fund allocation with SweepDesk, SMS and OTP with PrimeConnect, and private app distribution with Primers Store.

**Does Primers hold my money in Veltis One?**
No. The card holds only an ID. Money stays in the university's wallet system; Primers only sends a debit instruction after you confirm with your PIN or biometrics.

**Does it work without internet?**
Parts of it do: FlowDrop shares files offline, Velaji works on USSD, and PrimersGPT Desktop runs AI fully offline.

**Can developers build on Primers?**
Yes. Publish on Primers Store, add Sign in with Primers through the Primers ID API, and use PrimeConnect for messaging.

**Why use Primers OS instead of Windows or ChromeOS?**
It runs on older and cheaper machines, works offline, saves data, survives power cuts without losing work, and connects straight to campus life: ID, attendance, payments, safety and study tools under one Primers ID. It is free for students.

**Will my old laptop run Primers OS?**
Most 64-bit laptops from about 2012 onward should run it, with 2 GB RAM as the target minimum. Lite Mode keeps it smooth on weak machines.

**Can I make it look like Windows or Mac?**
Yes. Pick a layout in Settings and change themes, icons and fonts any time. Your setup follows your Primers ID to any campus computer.

**Can I still use Microsoft Word and other Windows apps?**
Word, Excel and PowerPoint files open and save in the built-in editor, and the web versions of Office work in the browser. For special Windows-only software your school may offer dual-boot or remote desktop.

**What is Exam Mode?**
A lockdown the university switches on for computer-based tests. Only the exam app runs, outside network access is blocked, and the session is logged.

**How do I contact Primers?**
Through the Primers Group website at primersgroup.ng. BraidUp support: braidup.primerscorperation@gmail.com

---

## 13. Glossary

| Term | Meaning |
|---|---|
| GMD | General Managing Director |
| Primers ID | Single Primers account across all products |
| Ask Primers | The launcher for Primers Lite GPT |
| PrimersGPT | Brand name for Presona, the offline desktop AI |
| Team Primers | Name Primers uses at hackathons and competitions |
| VUNA | Veritas University, Abuja |
| NACOS | Nigeria Association of Computing Students |
| CAC | Corporate Affairs Commission (Nigeria company registry) |
| PHC | Primary Health Centre |
| USSD | Short-code menu service that works on basic phones without data |
| Sweep | Automatic split of an inflow into sub-accounts by fixed percentages |
| Lite Mode | Low-resource mode that turns off effects and indexing on weak hardware |
| Study Mode | Timed focus mode that blocks distractions |
| Exam Mode | Institution-controlled lockdown for computer-based tests |
| Lab Mode | Shared-machine mode that wipes the session on logout |
| Course pack | One-click bundle of apps and settings for a course |
| Fleet console | Admin dashboard to manage many campus machines at once |

---

## 14. Machine-readable summary

```json
{
  "company": {
    "name": "Primers Group",
    "formerName": "Primers Corporation",
    "founded": 2024,
    "hq": "Abuja, Nigeria",
    "founder": "Jothan Jerry Kato",
    "domain": "primersgroup.ng",
    "registeredEntity": "Securelink Defence"
  },
  "platform": ["primers-id", "primers-lite-gpt", "primers-store", "presona", "flowdrop", "primeconnect"],
  "products": [
    {"id": "securelink", "module": "safety", "status": "in_build", "flagship": true},
    {"id": "veltis-one", "module": "campus", "status": "pilot_proposal"},
    {"id": "braidup", "module": "life", "status": "live"},
    {"id": "sendoff", "module": "life", "status": "live"},
    {"id": "velaji", "module": "health", "status": "live", "url": "https://velaji.vercel.app"},
    {"id": "primelink", "module": "insights", "status": "concept"},
    {"id": "rotawise", "module": "insights", "status": "prototype", "url": "https://rotawise-five.vercel.app"},
    {"id": "sweepdesk", "module": "finance", "status": "in_build"},
    {"id": "abuja-life", "module": "play", "status": "in_build"}
  ],
  "os": {
    "targets": {"minRamGB": 2, "baseInstallGB": 8, "minDiskGB": 16, "idleRamMB": 600, "coldBootSecondsSSD": 15, "tpmRequired": false},
    "modes": ["study", "exam", "lab", "lite", "battery_saver", "data_saver"],
    "layouts": ["windows_style", "mac_style", "chrome_style", "tablet"],
    "priceForStudents": "free",
    "institutionModel": "campus_licence"
  },
  "excluded": ["safecare", "vaultvisio", "surwash-me"],
  "roles": ["student", "staff", "org_admin", "institution_admin", "vendor", "responder", "health_worker", "developer", "primers_admin"]
}
```
