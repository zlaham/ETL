# Session 3 instructor guide

20 October 2026. Sixty minutes. The notebook is the deck. Do not ask anyone to write code.

Open `notebooks/session_03_transformations_ai.ipynb` from the project virtual environment and run it once before the room arrives. You want the font cache warm and `HTTP calls: 0` already proven on your machine.

## The hour in one line

Bronze is evidence. Silver decides which evidence is current and valid. Gold gives that decision a shape finance can reuse. A model may propose a product category. It does not get to publish one that failed the taxonomy, and it does not get to outrank merchandising or the CRM.

## Timeline

| Clock | Section | Do this live |
| --- | --- | --- |
| 0:00-0:05 | Recap and the question | Setup cell. Profile cell. Stop on the eight messy deliveries. |
| 0:05-0:18 | Staging, versions, quarantine | Staging output. Both `OL-1001-1` orderings. Disposition counts. The 7,374.50 versus 3,779.50 comparison. The chart if the room is with you. |
| 0:18-0:28 | Facts, dimensions, grain | `ORD-1003` has two lines. The catalog join goes from 11 rows to 13. Say the grain sentence out loud. |
| 0:28-0:43 | GenAI enrichment | Rules table. The tagged description. Accepted proposals and the review table. Cache: 7 misses, then 7 hits. |
| 0:43-0:54 | Gold | P103 published as manual. Revenue by category. Revenue by category and segment. The chart. The "without the model" table. |
| 0:54-1:00 | Run it again | The last code cell. Read the two closing sentences. |

## Numbers on your card

If a cell disagrees with this card, stop and rerun from the top before you explain a new theory.

| What | Value |
| --- | --- |
| Order deliveries | 29 |
| Distinct order lines in Bronze | 26 |
| Accepted / quarantined / policy / duplicate / superseded | 11 / 10 / 5 / 2 / 1 |
| Sum of every paid or completed delivery, including the bad ones | 7,374.50 |
| Published revenue | 3,779.50 |
| Smartphones / Accessories / Home / Personal Care | 3,426.00 / 211.00 / 89.00 / 53.50 |
| Consumer smartphones / Business smartphones | 1,948.00 / 1,478.00 |
| Business accessories / Consumer accessories | 87.00 / 124.00 |
| Home appliances, Wholesale | 89.00 |
| Personal care, Consumer | 53.50 |
| Revenue if model categories are rejected | Smartphones 3,426.00, Unclassified 353.50 |
| Rules / manual / model / fallback | 2,227.00 / 1,199.00 / 353.50 / 0.00 |
| `OL-1001-1` published price | 749.00, not 799.00 |
| Join to every catalog delivery vs current product | 13 vs 11 |
| Model selector | P104 through P110 |
| Cache | 7 misses, then 7 hits |
| HTTP calls | 0 |

`C100` and `C107` are both displayed as John Smith. They stay two keys.

## Section notes

### 1. Recap (5 minutes)

**Message.** Extraction worked. The report still cannot be trusted.

**Ask before you scroll.** "We extracted the data. Can we start building reports immediately?"

**Answer you want.** No. A sum over Bronze counts the retry, the replaced price, the cancellation, and rows with no customer or no product. Bronze stays intact so the number can be explained later.

**Pitfall.** Do not start cleaning on the projector before they have seen delivery 1, 2, and 3 of `OL-1001-1` side by side. The rest of the hour is about those three rows.

### 2. Transformation (13 minutes)

**Message.** Staging makes values comparable. It does not decide which row is real. Validation assigns every delivery a disposition, and "not in the fact" is not the same sentence as "the row was garbage."

**Live cells.**

- Staging. Point at `usd` becoming `USD`, `PAID` becoming `paid`, `15/10/2026 11:15` becoming 15 October, and `05/10/2026` staying ambiguous.
- Customers. Two John Smiths, two ids. Say that title case is presentation. It is not a match rule.
- `DISTINCT *` returns 29. Distinct on the business columns still leaves 799 and 749.
- Order by `ingested_at` and the winner is 799, because the stale version arrived last. Order by `source_updated_at` and the winner is 749.
- Disposition table. Read the five counts. Open quarantine only if someone asks what "invalid" means.
- 7,374.50 versus 3,779.50. This is the slide that earns the section.

**Policy, say it once.** Paid and completed sales enter the fact. Canceled orders stay out. A return is not stored as a negative sale. Pending and shipped are not recognized revenue yet. A real returns process needs its own fact. We refuse to invent one by flipping a sign.

**Timestamp contract.** Four forms are accepted. A missing zone means UTC because the contract says so. `05/10/2026` is quarantined because it is both 5 October and 10 May. Do not let the room "just pick European."

**Ask.** "Why is `SELECT DISTINCT` not enough?"

**Answer.** Distinct removes identical rows. A retry differs in `ingested_at`. An older price differs in `unit_price`. The business key is the order line. The current row is the latest source version of that key.

**Ask.** "One hundred thousand rows arrive and five hundred fail. Do we fail the pipeline?"

**Answer.** For this sales mart, no. Publish the valid current lines and keep the five hundred in quarantine with a reason. A payroll close might choose to stop. The failure mode to reject is deleting the five hundred and calling the load clean. Session 5 watches the rate. Session 6 decides how the run is marked.

**Pitfalls.**

- `stg_` is a modeling habit. It is not a fourth medallion layer. Silver is the trusted set. `accepted_records` is that set for orders. It does not start with `stg_`.
- `TRY_CAST('-1' AS INTEGER)` succeeds. The row is still rejected because a sale quantity has to be positive.
- `Canceled` maps to `cancelled` because we listed that synonym. `voided` does not, and it must not be guessed into a cancellation.
- The first failed rule wins so the counts stay readable. Production would keep every failed rule. Say that if an engineer calls the single reason naive. Agree, and move on.

### 3. Dimensions and facts (10 minutes)

**Message.** The operational database already exists and is the wrong shape for this question. `ORD-1003` is one checkout and two categories. The fact grain is one current, valid, recognized-revenue order line.

**Live cell.** The two lines of `ORD-1003`, then 11 versus 13 versus 11. P101 was delivered twice. Joining the fact to every catalog delivery double-counts the iPhone lines.

**Say the grain sentence.** "One row in `fct_order_items` is one valid order line in its current authoritative state."

**Ask.** "Why state the grain before creating the fact?"

**Answer.** The grain is what a row counts. An order-level fact hides one of `ORD-1003`'s categories or double-counts the other. Deduplicating the product is part of protecting the sentence.

**Ask.** "Why build `dim_customer` instead of joining CRM in every dashboard?"

**Answer.** One published name, segment, and identity. The next fact, returns or support, reuses it. That is a conformed dimension. The CRM stays the operational system. History and access control have one table to attach to.

**Keys.** The demo mints `customer_key` with `ROW_NUMBER()`. Say, out loud, that this is safe only because the member set is fixed for the hour. A new id that sorts into the middle would renumber everyone after it. Production inserts a key once and stores it. Session 4 is slowly changing dimensions. Do not teach types 1, 2, and 3 today.

**Pitfall.** A star schema is an access pattern: filter dimensions, aggregate the fact. It is not a claim that every warehouse table is a star.

### 4. GenAI enrichment (15 minutes)

**Message.** Rules publish the phones. The adapter rule returns `Accessories`, which is not in the taxonomy, so it publishes nothing. The model is for the residue, and its JSON is a proposal.

**Live cells.**

- Rules table. Stay on P102 (the ugly iPhone string still matches), P104 (`Accessories` is false), and P108 (the case has no keyword).
- Prompt cell. Read the allowed list and the line that says the description is untrusted data. Show the tagged `P108` input. Do not read the `urllib` function unless someone asks how the optional client is locked. The print says `Live request selected: False`.
- Enrichment cell. Selector is P104-P110. First pass 7 misses. Second pass 7 hits. Accepted includes P103's Mobile Phones suggestion. Review contains Wearables, a second P110 that is unsure, P999, and a row with no product id.

**Say this about the fixture.** It is precomputed output checked into the repo. The Wearables row is an example of an illegal answer, included so the gate has work to do. You are not demonstrating a particular vendor's model.

**Precedence, preview it here and show it in the next section.** Approved map, then a legal rule, then an accepted proposal, then `Unclassified`. `Unclassified` means we refused the proposal. `Other` is a bucket the model is allowed to choose. We do not coerce Wearables into Other.

**Cache.** The key is normalized description, taxonomy version, prompt version, model version. Product id is not in the key. The cache stores the proposal. Validation runs again on every build. Changing the prompt version changes the key. Show the two prefixes if you have thirty seconds.

**Ask.** "Would you call a model every time the pipeline sees the same product?"

**Answer.** No. Rules first, then the cache, then new or changed text, in batches, with a spend ceiling.

**Ask.** "The model says two customers are the same person. Do we merge them?"

**Answer.** No. Point back at C100 and C107. A model can nominate a pair. Identity stays an authoritative id plus a matching policy a person can audit.

**Table to leave up.** Rules are deterministic, cheap, and narrow. A model reaches wording the rules miss, costs money, and has to be stored to be audited. Both require validation. The model is not more accurate than a rule that already encodes the decision.

**Pitfalls.**

- Do not say "the AI categorized the catalog" and move on. P110 is unclassified. P103 is manual.
- Do not skip the review table. The trust boundary is the point of the section.
- A live call with temperature 0 is still not a reproducible system of record. The stored proposal is.

### 5. Gold (11 minutes)

**Message.** The business question is a join the grain made safe.

**Live cells.** P103 first: rule and model both say Smartphones, merchandising publishes Flagship Phones, method is `manual`. Then `dim_product`, then the two revenue queries, the chart, and the table that puts 353.50 into Unclassified when model output is rejected.

**While the category chart is up.** Smartphones did not need the model. The 353.50 did. That is the cost and the value on one slide.

**Surrogate reminder, one sentence.** These keys are row numbers. The fact joins them. Tomorrow's new customer must not renumber yesterday's fact.

**Date dimension.** It is generated for October 2026. It is not "the dates that happened to appear." The date key is the UTC date, because that is the contract. Another business zone would be named, not implied.

**Pitfall.** `total_amount` is `quantity * unit_price`. There is no source total to trust. If someone says the source total should win, point at Session 2's mismatched totals and at the 799 that would have won here.

### 6. Close (6 minutes)

Run the last code cell. It checks the certified 11 lines, rejects canceled and returned ids, checks foreign keys, checks the taxonomy, checks that the John Smiths were not merged, rebuilds the whole pipeline, and requires the same signature.

**Read, do not paraphrase, the last two sentences of the notebook.**

**If you have time for one of the four questions, use the model-retirement question.** The report reads the category that was published, with the model, prompt, and taxonomy versions on the row. Asking a new model the old question is a different number. Reprocessing is a release.

**The other three, short if you state them yourself.**

- Running twice must not append. The build replaces tables. `ingested_at` comes from the envelope, not from the clock.
- Five million descriptions do not each get a call. Rules, cache, residue, batches, a ceiling.
- A suggested segment that disagrees with CRM loses. The customer dimension is built from CRM. The model was not given that authority.

## If you are behind

At minute 40, still in the rules:

1. Skip the quarantine example table. Keep the five disposition counts and 7,374.50 versus 3,779.50.
2. Skip scrolling the customer dimension. The two John Smiths already landed.
3. Say the grain sentence and show the 11 versus 13 join. Skip the operational-schema drawing if you already said it.
4. Do not open the live HTTP function.
5. Show the review table, not every accepted row.
6. Run the revenue queries, the "without the model" table, and the last code cell.
7. Read the closing sentences.

Protect, in order: the 799 versus 749 ordering, the disposition counts, the grain, the rejected Wearables row, and the category revenue.

## If you are ahead

- Two different prices with the same `source_updated_at` would be a conflict, not a tie-break. We do not have that row. Say what you would do: quarantine the business key.
- A returns fact would carry the returned line as its own grain, linked to the sale, with its own sign policy. Do not design it on the whiteboard.
- Conformed `dim_customer` is why support and finance can argue about the same person.
- An evaluation set is a merchandiser-labeled sample scored before a new prompt is allowed to publish. The fixture is not that sample.
- Session 4 owns attribute history. Session 5 owns incremental processing and monitors. Session 6 owns the run. Session 7 owns who can read Gold.

## Do not

- Do not modify Session 2 to "make the data more realistic."
- Do not present the fixture as a live call.
- Do not turn on `LIVE_LLM_ENABLED` in the room.
- Do not let `ROW_NUMBER()` pass as a production key strategy.
- Do not merge customers on a cleaned name.
- Do not call every excluded row an error.
- Do not teach Spark, Kafka, or a platform choice. DuckDB is here because it speaks SQL in this process.
