// Verifies clients/chat.html by driving its real handler code, under a minimal
// DOM shim, against SSE frames a real server actually produced. It checks the
// five contract properties the client's own header promises to preserve -- the
// ones a protocol loses first when you make it look like a chat window.
//
//     node clients/verify_chat_client.mjs
//
// Optional: nothing else in this repo needs node, and `pytest` does not run
// this. It exists because clients/chat.html is kept code, and "it looked right
// in a browser once" is not a check anyone else can repeat.
//
// FRAMES below were captured from `scripts/serve_reference_client_demo.py`
// (fake generation, zero quota) and are pasted in verbatim so this file is
// self-contained. They are a fixture, not a second source of truth: the
// contract itself is guarded by tests/test_stream_contract.py. If an event's
// shape changes there, re-capture these by streaming three requests off that
// demo server and replacing the literal.
import fs from "node:fs";
import assert from "node:assert/strict";

const HTML = fs.readFileSync(new URL("./chat.html", import.meta.url), "utf8");
const FRAMES = {
  "turn1": [
    [
      "sources",
      {
        "chunks": [
          {
            "title": "Deposit",
            "url": "https://www.maryvillecollege.edu/deposit/",
            "silo": [
              "admissions"
            ],
            "heading_path": [
              "Admissions",
              "Deposit"
            ],
            "rerank_score": null,
            "last_verified": "2026-08-14",
            "stale": false
          },
          {
            "title": "Financial Aid",
            "url": "https://www.maryvillecollege.edu/financial-aid/",
            "silo": [
              "admissions"
            ],
            "heading_path": [
              "Admissions",
              "Deposit"
            ],
            "rerank_score": null,
            "last_verified": "2024-01-05",
            "stale": true
          }
        ],
        "rewritten_query": null
      }
    ],
    [
      "token",
      {
        "text": "The deposit is $300. https://www.maryvillecollege.edu/deposit/"
      }
    ],
    [
      "citation",
      {
        "claim_span": [
          21,
          62
        ],
        "source_url": "https://www.maryvillecollege.edu/deposit/",
        "chunk_id": "c1"
      }
    ],
    [
      "done",
      {
        "latency_ms": {
          "embed": 0.003300025127828121,
          "dense": 0.0023999891709536314,
          "bm25": 0.001300009898841381,
          "literal": 0.000600004568696022,
          "fuse": 0.026699999580159783,
          "reform": 0.001400010660290718,
          "rerank": 0.03860000288113952,
          "generate_ttft": 0.04199999966658652,
          "generate_total": 0.0481999886687845,
          "e2e": 0.892100011697039
        },
        "server_ns": {
          "total": 5000000,
          "prompt_eval": 1000000,
          "eval": 4000000
        },
        "refused": false,
        "schema_version": "v1"
      }
    ]
  ],
  "turn2": [
    [
      "sources",
      {
        "chunks": [
          {
            "title": "Deposit",
            "url": "https://www.maryvillecollege.edu/deposit/",
            "silo": [
              "admissions"
            ],
            "heading_path": [
              "Admissions",
              "Deposit"
            ],
            "rerank_score": null,
            "last_verified": "2026-08-14",
            "stale": false
          },
          {
            "title": "Financial Aid",
            "url": "https://www.maryvillecollege.edu/financial-aid/",
            "silo": [
              "admissions"
            ],
            "heading_path": [
              "Admissions",
              "Deposit"
            ],
            "rerank_score": null,
            "last_verified": "2024-01-05",
            "stale": true
          }
        ],
        "rewritten_query": "What is the deposit? When is it due?"
      }
    ],
    [
      "token",
      {
        "text": "The deposit is $300. https://www.maryvillecollege.edu/deposit/"
      }
    ],
    [
      "citation",
      {
        "claim_span": [
          21,
          62
        ],
        "source_url": "https://www.maryvillecollege.edu/deposit/",
        "chunk_id": "c1"
      }
    ],
    [
      "done",
      {
        "latency_ms": {
          "embed": 0.0031999952625483274,
          "dense": 0.0010999792721122503,
          "bm25": 0.000600004568696022,
          "literal": 0.000500003807246685,
          "fuse": 0.015700003132224083,
          "reform": 0.005099980626255274,
          "rerank": 0.03890000516548753,
          "generate_ttft": 0.02340000355616212,
          "generate_total": 0.03020002623088658,
          "e2e": 1.2048000062350184
        },
        "server_ns": {
          "total": 5000000,
          "prompt_eval": 1000000,
          "eval": 4000000
        },
        "refused": false,
        "schema_version": "v1"
      }
    ]
  ],
  "refusal": [
    [
      "sources",
      {
        "chunks": [
          {
            "title": "Deposit",
            "url": "https://www.maryvillecollege.edu/deposit/",
            "silo": [
              "admissions"
            ],
            "heading_path": [
              "Admissions",
              "Deposit"
            ],
            "rerank_score": null,
            "last_verified": "2026-08-14",
            "stale": false
          },
          {
            "title": "Financial Aid",
            "url": "https://www.maryvillecollege.edu/financial-aid/",
            "silo": [
              "admissions"
            ],
            "heading_path": [
              "Admissions",
              "Deposit"
            ],
            "rerank_score": null,
            "last_verified": "2024-01-05",
            "stale": true
          }
        ],
        "rewritten_query": null
      }
    ],
    [
      "refusal",
      {
        "reason": "model",
        "office": "Admissions",
        "contact_url": "https://www.maryvillecollege.edu/admissions/apply/",
        "email": "admissions@maryvillecollege.edu"
      }
    ],
    [
      "done",
      {
        "latency_ms": {
          "embed": 0.002200016751885414,
          "dense": 0.0017999846022576094,
          "bm25": 0.000500003807246685,
          "literal": 0.000300002284348011,
          "fuse": 0.028300011763349175,
          "reform": 0.0013999815564602613,
          "rerank": 0.032899988582357764,
          "generate_ttft": 0.02750000567175448,
          "generate_total": 0.03370002377778292,
          "e2e": 47.85000000265427
        },
        "server_ns": {
          "total": 5000000,
          "prompt_eval": 1000000,
          "eval": 4000000
        },
        "refused": true,
        "schema_version": "v1"
      }
    ]
  ]
};

/* ------------------------------------------------------------- DOM shim */
class TextNode {
  constructor(t) { this.data = String(t); this.parent = null; }
  get textContent() { return this.data; }
  get isConnected() { return !!this.parent; }
}
class Node {
  constructor(tag) {
    this.tag = tag; this.kids = []; this.parent = null; this.className = "";
    this.hidden = false; this.attrs = {}; this.style = {}; this.title = ""; this.id = "";
    this.href = ""; this.target = ""; this.rel = ""; this.open = false; this.disabled = false;
  }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n === ROOT; }
  append(...kids) {
    for (const k of kids) {
      if (k && k.__fragment) { this.append(...k.kids); continue; }
      k.parent = this; this.kids.push(k);
    }
  }
  replaceChildren(...kids) { this.kids = []; this.append(...kids); }
  remove() { if (this.parent) { this.parent.kids = this.parent.kids.filter((k) => k !== this); this.parent = null; } }
  set textContent(v) { this.kids = [Object.assign(new TextNode(v), { parent: this })]; }
  get textContent() { return this.kids.map((k) => k.textContent).join(""); }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener() {}
  focus() {}
  // Flattened description of the rendered subtree, for assertions.
  shape() {
    return this.kids.map((k) => (k instanceof TextNode ? `#${k.data}` : `${k.tag}.${k.className}`)).join(" ");
  }
  find(pred) {
    if (pred(this)) return this;
    for (const k of this.kids) { const hit = k instanceof Node ? k.find(pred) : null; if (hit) return hit; }
    return null;
  }
}
const ROOT = new Node("html");
const byId = {};
for (const id of ["banner", "thread", "empty", "scroll", "send", "stop", "token",
                  "question", "turncount", "composer", "reset"]) {
  const n = new Node("div"); n.id = id; n.value = ""; byId[id] = n; ROOT.append(n);
}
byId.token.value = "demo-token-not-a-secret";

globalThis.document = {
  getElementById: (id) => byId[id] ?? null,
  createElement: (t) => new Node(t),
  createTextNode: (t) => new TextNode(t),
  createDocumentFragment: () => Object.assign(new Node("#fragment"), { __fragment: true }),
  querySelectorAll: () => [],
};
globalThis.location = { origin: "http://localhost" };
globalThis.AbortController = class { constructor() { this.signal = {}; } abort() {} };

/* ---------------------------------------------- load the client's own code */
// `\r?\n`, because git on Windows may well hand this file out with CRLF
// endings and a checkout should not silently stop verifying anything.
const matched = HTML.match(/<script>\r?\n([\s\S]*?)\r?\n<\/script>/);
assert.ok(matched, "could not find the client's <script> block in chat.html");
const src = matched[1];
const exposed = src + "\n;globalThis.__C = { newTurn, onSources, onToken, onCitation, onRefusal, onDone, renderAnswer, HANDLERS, history };";
new Function(exposed)();
const C = globalThis.__C;

/* --------------------------------------------------------------- the checks */
let checks = 0;
const ok = (name) => { checks++; console.log("  PASS  " + name); };

// ---- Property 1: sources are on screen before any token exists -----------
{
  const t = C.newTurn("What is the deposit?");
  const [sourcesType, sourcesData] = FRAMES.turn1[0];
  assert.equal(sourcesType, "sources");
  C.onSources(t, sourcesData);
  assert.ok(!t.sources.hidden, "sources block must be visible");
  assert.match(t.sources.textContent, /source/);
  assert.equal(t.answer.textContent, "", "no answer text may exist yet");
  assert.ok(t.sources.textContent.includes(sourcesData.chunks[0].title));
  ok("property 1 — sources rendered, answer still empty");

  // the stale chunk the demo plants must be badged, not silently shown as fresh
  const stale = sourcesData.chunks.findIndex((c) => c.stale);
  assert.ok(stale >= 0, "demo should include one stale chunk");
  assert.match(t.sources.textContent, /out of date/);
  ok("stale source badged");
}

// ---- Property 2: citations spliced at the server's claim_span offsets -----
{
  const t = C.newTurn("What is the deposit?");
  for (const [type, data] of FRAMES.turn1) C.HANDLERS[type]?.(t, data);
  const cite = FRAMES.turn1.find(([ty]) => ty === "citation")[1];
  const full = FRAMES.turn1.filter(([ty]) => ty === "token").map(([, d]) => d.text).join("");
  const [s, e] = cite.claim_span;

  // The rendered answer must be the token stream verbatim once the numbered
  // citation markers (added chrome, not model output) are excluded.
  const streamText = (n) =>
    n.kids.map((k) => (k instanceof TextNode ? k.data : k.tag === "sup" ? "" : streamText(k))).join("");
  assert.equal(streamText(t.answer), full, "rendered text must equal the token stream exactly");
  const anchor = t.answer.find((n) => n.tag === "a" && n.className === "cite");
  assert.ok(anchor, "the cited span must be an anchor");
  assert.equal(anchor.textContent, full.slice(s, e), "anchor must cover exactly [start, end)");
  assert.equal(anchor.href, cite.source_url);
  const mark = t.answer.find((n) => n.tag === "sup");
  assert.equal(mark.textContent, "1", "marker numbers the source's position in this turn's list");
  ok(`property 2 — span [${s},${e}) spliced at the server's offsets, not re-parsed`);

  // a span that has not fully arrived yet must not be spliced
  const partial = C.newTurn("x");
  C.onSources(partial, FRAMES.turn1[0][1]);
  C.onToken(partial, { text: full.slice(0, s + 2) });
  C.onCitation(partial, cite);
  assert.equal(partial.answer.find((n) => n.tag === "a" && n.className === "cite"), null);
  assert.equal(partial.answer.textContent, full.slice(0, s + 2));
  ok("citation past the end of the text so far is held, not mis-spliced");
}

// ---- Property 3: refusal built from structured fields --------------------
{
  const t = C.newTurn("Is there parking available?");
  const order = FRAMES.refusal.map(([ty]) => ty);
  assert.deepEqual(order, ["sources", "refusal", "done"]);
  for (const [type, data] of FRAMES.refusal) C.HANDLERS[type]?.(t, data);
  const r = FRAMES.refusal.find(([ty]) => ty === "refusal")[1];
  const box = t.slot.find((n) => n.className === "refusal");
  assert.ok(box, "refusal card must render");
  assert.match(box.textContent, new RegExp(r.office));
  assert.match(box.textContent, new RegExp(r.email.replace(/[.@]/g, "\\$&")));
  assert.match(box.textContent, new RegExp(`refusal pathway: ${r.reason}`));
  const mail = box.find((n) => n.tag === "a" && n.href.startsWith("mailto:"));
  assert.equal(mail.href, "mailto:" + r.email);
  assert.equal(t.answer.textContent, "", "a refusal renders no answer text at all");
  ok("property 3 — office, contact and email read from fields, not from prose");
}

// ---- Property 4: a stage that did not run shows an em dash, never 0 ms ---
{
  const t = C.newTurn("q");
  C.onSources(t, FRAMES.turn1[0][1]);
  const done = structuredClone(FRAMES.turn1.find(([ty]) => ty === "done")[1]);
  done.latency_ms.reform = null;     // the contract's own null case
  done.latency_ms.rerank = 0.0;      // and the 0.0 it must not look like
  C.onDone(t, done);
  const grid = t.meta.find((n) => n.className === "timings");
  const cells = grid.kids.map((c) => c.textContent);
  assert.ok(cells.includes("reform —"), `expected 'reform —', got ${JSON.stringify(cells)}`);
  assert.ok(cells.includes("rerank 0 ms"), "0.0 must still read as 0 ms");
  assert.ok(!t.meta.hidden);
  ok("property 4 — null stage renders '—', 0.0 renders '0 ms'");

  // schema drift must raise the banner rather than be read as v1
  byId.banner.hidden = true;
  const drifted = structuredClone(done); drifted.schema_version = "v2";
  C.onDone(C.newTurn("q2"), drifted);
  assert.equal(byId.banner.hidden, false);
  assert.match(byId.banner.textContent, /v2/);
  ok("schema_version mismatch raises the banner");
}

// ---- memory: the re-answer cost is disclosed, not hidden -----------------
{
  C.history.push("What is the deposit?");      // one prior turn held
  const t = C.newTurn("When is it due?");
  assert.equal(t.priorTurns, 1);
  for (const [type, data] of FRAMES.turn2) C.HANDLERS[type]?.(t, data);
  assert.match(t.meta.textContent, /1 prior turn re-answered/);
  assert.match(t.sources.textContent, /Retrieved on: “What is the deposit\? When is it due\?”/);
  ok("memory — prior-turn re-answer cost and the rewritten query are both shown");
}

// ---- a url the client should refuse to turn into a link ------------------
{
  const t = C.newTurn("q");
  const evil = structuredClone(FRAMES.turn1[0][1]);
  evil.chunks[0].url = "javascript:alert(1)";
  C.onSources(t, evil);
  assert.equal(t.sources.find((n) => n.tag === "a" && n.href.startsWith("javascript:")), null);
  ok("non-http(s) source url is rendered as text, never as an href");
}

// ---- Property 5: SSE is read over fetch, never EventSource ---------------
{
  // The comment explaining why EventSource is unusable mentions it by name, so
  // this looks for a construction rather than the word.
  assert.ok(!/new\s+EventSource/.test(src), "EventSource is GET-only and cannot send X-API-Key");
  assert.match(src, /fetch\(ENDPOINT, \{/, "the stream must be read over fetch");
  // The page is keyless: the server adds the token to /ask itself
  // (scripts/serve_chat.py), so the page must neither ask for a key nor send one.
  assert.ok(!/id="token"/.test(HTML), "the page must not render an API key field");
  assert.ok(!/["']x-api-key["']\s*:/i.test(src), "the page must not send an API key");
  assert.match(src, /buf\.indexOf\("\\n\\n"\)/, "frames must be split on the SSE blank line");
  // Same-origin only, deliberately: a configurable base URL would be a way to
  // make this page send its API key somewhere else.
  assert.match(src, /const ENDPOINT = "\/ask"/);
  assert.ok(!/location\.search|URLSearchParams/.test(src), "no endpoint override taken from the URL");
  ok("property 5 — hand-rolled SSE over fetch, same-origin, key in a header");
}

// ---- a stream that ends without `done` is a failure, not an answer -------
{
  // An upstream generation connection torn mid-answer ends the SSE body with
  // no terminal event (`mcrag/generate/ollama_cloud.py` raises GenerationError
  // out of the service's stream, and FastAPI just stops writing). A truncated
  // reply must not read as a finished one, and the question must not join the
  // memory -- otherwise the next turn is decontextualized against an answer
  // the server never actually finished giving.
  const t = C.newTurn("q");
  const truncated = FRAMES.turn1.filter(([type]) => type !== "done");
  assert.ok(truncated.length < FRAMES.turn1.length, "the fixture has no done frame to drop");
  for (const [type, data] of truncated) C.HANDLERS[type]?.(t, data);
  assert.equal(t.sawDone, false, "no done frame arrived, so the turn must not be marked complete");
  // The guard itself lives inside `ask()`'s fetch loop, which the DOM shim
  // does not drive, so it is read out of the source rather than executed.
  const guard = src.indexOf("if (!t.sawDone)");
  const push = src.indexOf("history.push(question)");
  assert.ok(guard > -1, "ask() must guard on sawDone before banking the turn");
  assert.ok(push > guard, "the guard must run before the turn joins the memory");
  assert.ok(
    /if \(!t\.sawDone\) \{\s*throw new Error/.test(src),
    "a stream with no `done` must throw rather than fall through",
  );
  ok("a stream that never sent `done` fails the turn instead of banking it");
}

console.log(`\n${checks} checks passed`);
