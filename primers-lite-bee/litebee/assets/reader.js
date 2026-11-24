/* Primers Lite Bee — reader mode.
 * Keeps the main article text of the current page and drops everything
 * else (menus, ads, scripts, embeds). Runs only on the page's own content. */
(function () {
  "use strict";
  var candidates = document.querySelectorAll("article, main, [role=main], .post, .article, .content, #content, .entry-content, body");
  var best = null, bestScore = 0;
  for (var i = 0; i < candidates.length; i++) {
    var el = candidates[i], score = 0;
    var ps = el.querySelectorAll("p");
    for (var j = 0; j < ps.length; j++) {
      var len = (ps[j].textContent || "").trim().length;
      if (len > 40) score += len;
    }
    if (score > bestScore) { best = el; bestScore = score; }
  }
  if (!best || bestScore < 200) return "no-article";

  var clone = best.cloneNode(true);
  var junk = clone.querySelectorAll("script, style, noscript, iframe, form, nav, aside, footer, header, button, svg, video, audio, object, embed, [aria-hidden=true], .ad, .ads, .advert, .share, .social, .comments");
  for (var k = 0; k < junk.length; k++) junk[k].remove();
  var all = clone.querySelectorAll("*");
  for (var m = 0; m < all.length; m++) {
    var attrs = Array.prototype.slice.call(all[m].attributes);
    for (var n = 0; n < attrs.length; n++) {
      var name = attrs[n].name;
      if (name !== "href" && name !== "src" && name !== "alt") all[m].removeAttribute(name);
      if ((name === "href" || name === "src") && /^\s*javascript:/i.test(attrs[n].value)) all[m].removeAttribute(name);
    }
  }

  var title = document.title;
  var doc = document.implementation.createHTMLDocument(title);
  var style = doc.createElement("style");
  style.textContent = "body{margin:0;background:#f7f3ea;color:#1b1b1b;font:19px/1.65 'Noto Serif',Georgia,serif}" +
    "main{max-width:680px;margin:0 auto;padding:32px 20px}h1{font:700 30px/1.25 'Noto Sans',sans-serif;margin:0 0 20px}" +
    "img{max-width:100%;height:auto}a{color:#8a5a00}pre,code{white-space:pre-wrap;font-size:15px}" +
    "@media (prefers-color-scheme: dark){body{background:#0a1a27;color:#f4efe6}a{color:#e6ad39}}";
  doc.head.appendChild(style);
  var main = doc.createElement("main");
  var h1 = doc.createElement("h1");
  h1.textContent = title;
  main.appendChild(h1);
  main.appendChild(doc.importNode(clone, true));
  doc.body.appendChild(main);
  document.replaceChild(document.importNode(doc.documentElement, true), document.documentElement);
  return "ok";
})();
