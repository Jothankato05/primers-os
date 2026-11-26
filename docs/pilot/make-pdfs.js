#!/usr/bin/env node
// Render the pilot kit's printable pages to A4 PDFs next to them, and check
// each fits the pages it is meant to (the invigilator card and the install
// checklist: one page; the feedback forms: one page each).
//
//   node docs/pilot/make-pdfs.js
//
// Needs Node and Playwright with Chromium (npm install playwright).
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const pages = { "invigilator-card.html": 1, "install-checklist.html": 1, "feedback-form.html": 2 };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const bad = [];
  for (const [name, expected] of Object.entries(pages)) {
    await page.goto("file://" + path.join(__dirname, name));
    await page.emulateMedia({ media: "print" });
    const pdf = await page.pdf({ format: "A4", preferCSSPageSize: true, printBackground: true });
    fs.writeFileSync(path.join(__dirname, name.replace(".html", ".pdf")), pdf);
    const count = (pdf.toString("latin1").match(/\/Type\s*\/Page[^s]/g) || []).length;
    console.log(`${name}: ${count} page(s), expected ${expected}`);
    if (count !== expected) bad.push(name);
  }
  await browser.close();
  if (bad.length) {
    console.error("too long: " + bad.join(", "));
    process.exit(1);
  }
})();
