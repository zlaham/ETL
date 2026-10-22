# Session 4 instructor guide

Sixty minutes. The notebook is the deck. Do not ask anyone to write code.

Open `notebooks/04_Gold_Layer_and_Dimensional_Modeling.ipynb` from the project virtual environment and run it once before the room arrives. You want the font cache warm and the setup cell already showing `Silver source: checked_in_silver`.

## The hour in one line

Session 3 decided which order line is revenue and what category it carries. Gold decides which version of a customer and a product that line points at, and it refuses to let a later change, a return, or a second mart rewrite the number.

## Timeline

| Clock | Section | Do this live |
| --- | --- | --- |
| 0:00-0:06 | The star we already published | Setup. The 11 lines. Stop on the row-number warning. |
| 0:06-0:12 | What Gold is | The diagram, the grain table, the bus. |
| 0:12-0:22 | Durable keys | Original keys match. Then C050. C100 stays 1. |
| 0:22-0:36 | Attribute history | C100's name. C101's two versions. The 1,199. Then P104 and the 114. |
| 0:36-0:46 | Facts and returns | Same key on the lotion. Different keys in the scenario. The 749 in suspense. |
| 0:46-0:54 | Marts | Daily bars, weekend 889, KPI, mart equals fact. |
| 0:54-1:00 | Run it again | Second signature. Read the closing sentences. |

## Numbers on your card

If a cell disagrees with this card, stop and rerun from the top before you explain a new theory.

| What | Value |
| --- | --- |
| Sales lines / orders / units | 11 / 10 / 18 |
| Gross / return / net | 3,779.50 / 12.50 / 3,767.00 |
| Average order gross | 377.95 |
| 15 Oct Thursday | 2,035.00 |
| 16 Oct Friday | 855.50 |
| 17 Oct Saturday | 140.00 |
| 18 Oct Sunday | 749.00 |
| Weekend | 889.00 |
| Smartphones | 3,426.00 |
| Accessories as sold / as current | 211.00 / 97.00 |
| Power as current | 114.00 |
| Home appliances / personal care | 89.00 / 53.50 |
| Consumer phones as sold / as current | 1,948.00 / 749.00 |
| Business phones as sold / as current | 1,478.00 / 2,677.00 |
| C100 key, after the name correction | 1, John A. Smith, one version |
| C101 Consumer key / Business key | 2 through 16 Oct / 9 from 17 Oct |
| C050 row number if rebuilt / durable key | 1 / 10 |
| P104 accessories key / Power key | 4 through 17 Oct / 11 from 18 Oct |
| Lotion return | R-1005-1, 12.50, sold Friday, returned Monday, same customer key |
| Scenario, not in the KPI | Priya's 1,199.00 would return on key 9 |
| Suspense | OL-1026-1, C109, 749.00 |
| Registry rows | 21 (10 customer, 11 product) |
| Unknown key | -1, on no sales fact |

`OL-1001-1` is still 749.00. `C107` is still John Smith. The two ids were not merged.

## Section notes

### 1. The star we already published (6 minutes)

**Message.** Extraction worked. Silver worked. The report from last hour is a real number. It is not yet a number we can defend next month.

**Ask before you scroll.** "Session 3 already returned revenue by category and segment. Why are we still modeling?"

**Answer you want.** Because the keys were row numbers over a fixed set, and every attribute on the dimension was the current one. A new customer, a segment change, or a category change either renumbers history or rewrites it.

**Leave up.** The 11 lines and USD 3,779.50. Say that Gold does not get to rediscover that total.

**Pitfall.** Do not re-open quarantine, the model, or the 799-versus-749 ordering. Point at Session 3 if someone asks. The 749 is an input now.

### 2. What Gold is (6 minutes)

**Message.** Gold is the model other teams are allowed to query. Silver is the trusted input to that model.

**Live.** The diagram, then the grain table, then the bus. Read the sales grain sentence out loud. It is the same sentence as Session 3, with one addition: the foreign keys are the versions in effect on the order date.

**Ask.** "Why write the grain down as a row in a table?"

**Answer.** So a disagreement about a duplicate has a sentence to point at. The bus says which fact uses which role of a shared dimension. `dim_date` is one table. Order date and return date are two roles.

**Pitfall.** A star schema is the access path for this mart. It is not a claim that every Gold table is a star. The suspense table is Gold, and it is not a fact.

### 3. Durable keys (10 minutes)

**Message.** The platform owns the surrogate. The source owns the business key. The fact stores the surrogate.

**Live cells.** The original eight: row number and durable key match. Then the rebuilt set that includes C050: C100's row number becomes 2 and the stored key stays 1. C050 receives 10, which is the next key, not the first key in alphabetical order. Then the unknown member, key -1.

**Say this once.** A brand-new classroom database still assigns C100 = 1 because the allocator loads the Silver population first and the change feed second. It does not sort the final member set and number it. The second publish is what proves the keys were stored: the registry does not grow, and the facts are replaced.

**Ask.** "C050 has no orders. Why is he in the dimension?"

**Answer.** A conformed dimension can know a party before a fact needs him. The next fact, returns or support, reuses the same key. An empty fact for a dimension member is legal. A fact row with no dimension member is not, for this mart.

**Pitfall.** Do not let `ROW_NUMBER()` survive as "fine for now." The fragile view is the counterexample. Agree that a hash of the business key is another durable scheme, and do not design it on the whiteboard.

### 4. Attribute history (14 minutes)

**Message.** Some changes correct a value. Some changes are a new business state. The model has to know which is which before the row is written.

**Live, in this order.**

1. C100. One version. The name is John A. Smith. The key is still 1. The October sales now display the corrected name.
2. Say the tradeoff in one sentence: a Type 1 correction does not retain the previous spelling or the date we learned about it. We chose that because a misspelled legal name is not a state we want revenue to remember. If the date mattered, it would be Type 2.
3. C101. Version 2 is Business from 17 October. Version 1 is Consumer through 16 October. Her phone was 15 October, so the fact points at key 2.
4. The segment chart. As sold: Consumer phones 1,948.00, Business phones 1,478.00. As the current segment: Consumer 749.00, Business 2,677.00. The 1,199.00 moved. Gold's published reading is the first one.
5. P104. Key 4 is Electronics Accessories through 17 October. Key 11 is Power from 18 October. Both adapter lines are before the 18th, so they keep key 4. The category chart: Accessories 211.00 as sold, 97.00 if you join to Power. The 114.00 is the whole lesson.

**Ask.** "Finance asks for revenue by the segment the customer is in today. Which query is that?"

**Answer.** The as-is join, from the fact's customer to `is_current`. It is a legal question. It is a different question. The column has to say so. We do not store it as `mart_sales_by_day_category`.

**Ask.** "Why isn't every change Type 2?"

**Answer.** Type 2 keeps every spelling, every country-code cleanup, and every whitespace fix as a version the fact might miss or double-count. Type 1 is for corrections where the previous value must not remain queryable. The choice is made per attribute, in advance.

**Pitfall.** Effective dates here are calendar dates. A change and a sale on the same morning are out of scope; say so if an engineer asks, and do not invent a timestamp precedence on the whiteboard. The end date is inclusive. The next version starts the next day. C101 has no gap and no overlap.

**Do not teach** Type 3, Type 4, or Type 6. If someone names Type 3, say it keeps a previous-value column on one row, and this hour chose two rows for the segment.

### 5. Facts and returns (10 minutes)

**Message.** The sales grain does not become a notebook where we erase events. A return is a second fact on the same dimensions.

**Live.**

- `OL-1005-1` sold 3 units on Friday 16 October and took 1 unit back on Monday 19 October. Both rows point at the same customer key. That is a conformed dimension doing its job.
- The sale still shows 37.50. Net personal care is a KPI calculation, 53.50 minus 12.50, not an edited fact row.
- The scenario: if Priya's phone were returned on 18 October, the sale would stay on key 2 (Consumer) and the return would land on key 9 (Business). Subtracting those inside one segment is a second business rule. We did not hide it inside the fact, and we did not publish that return.
- Suspense: `OL-1026-1`, customer C109, 749.00. The unknown member exists so a query can name a missing party. Recognized revenue still requires a real customer. The 749 is not in the 3,779.50.

**Ask.** "Do we update the sale, insert a negative sale, or insert a return?"

**Answer.** Insert a return. Updating the sale destroys the fact that three units were sold. A negative row in the sales fact makes every consumer remember a sign convention. A return fact has its own grain, its own date role, and its own quantity check: you cannot return more than you sold.

**Say the other two fact shapes in four sentences, then leave them.** A transaction fact records an event, which is what both of these are. A periodic snapshot records a level at a point in time; units still out on the lotion line are 2, and that level is derivable, so we did not store a third fact. An accumulating fact holds milestones of one process. Pending and shipped were excluded in Session 3 because they are not recognized revenue. They do not become columns on this fact.

**Pitfall.** The return joins the dimension versions in effect on the return date, not the keys copied off the sale. The lotion happens to be the same key. The scenario is there so the room does not learn the wrong rule from the coincidence.

### 6. Marts (8 minutes)

**Message.** A mart is a query we are willing to store. It is built from the fact. It does not get its own definition of revenue.

**Live.** The daily bars. Saturday and Sunday are the warning color: 140.00 and 749.00, together 889.00. Then the KPI row. Then the reconciliation: the mart sums to 3,779.50, the same figure as the fact. Net is 3,767.00 because the return is applied once, in the KPI, at company level.

**Ask.** "The daily mart and a dashboard both claim to be Gold, and they disagree. Which one is wrong?"

**Answer.** The one that is not the fact, until someone shows a definition the fact violated. A dashboard that joins the current product category will report Power and will be short 114.00 of Accessories. That dashboard is answering as-is. It does not get to replace the mart.

**Pitfall.** Average order gross is 3,779.50 divided by 10 orders, 377.95. It is not divided by 11 lines, and it is not net of the return. Say the denominator out loud.

### 7. Close (6 minutes)

Run the last code cell. It publishes again without resetting the registry. The signature matches. Registry rows stay 21.

**Read the last two sentences of the notebook.**

**If you have time for one extra question, use the restatement question.** C109's line is waiting. When the customer arrives, a restatement run can assign a real key and the fact can grow. That run is a release. This build does not do it silently, and it does not invent the revenue today.

## If you are behind

At minute 40, still on the segment chart:

1. Skip the bus table. The diagram and the grain sentence are enough.
2. Skip scrolling the original eight keys. Show only C100's 2 versus 1.
3. Show C101 and the segment chart. Skip the speech about Type 3.
4. Show P104's two rows and the 211 versus 97. You can skip the category chart if the table is up.
5. Show the lotion return and the suspense row. Skip the scenario only if you must; it is the better of the two return points.
6. Show the KPI and the reconciliation. Skip the daily chart.
7. Run the last cell and read the closing sentences.

Protect, in order: C100's key stays 1, the 1,199.00 stays on Consumer, the 114.00 stays on Accessories, the return does not edit the sale, the 749.00 stays in suspense, the mart equals 3,779.50.

## If you are ahead

- A second Type 2 change chains the same way: close the open version the day before, append, allocate the next key. The sample has one change per entity so the room can see the edge.
- Deleting the database and loading C050 inside the Silver file, instead of the change feed, would make him part of phase 1 and would move the initial numbers. The phase is the arrival, and it has to be explicit.
- Company-level net subtracts returns from gross. Net by the original segment would require a rule for the scenario, where the sale is Consumer and the return is Business. We did not publish that rule.
- Session 5 owns incremental processing and monitors. Session 6 owns the run. Session 7 owns who can read Gold.

## Do not

- Do not modify Session 2 or Session 3 to make this hour easier.
- Do not re-teach quarantine or the model.
- Do not merge C100 and C107.
- Do not publish the suspense line into the KPI.
- Do not store the return as a negative sales row.
- Do not present the as-is figures as the mart.
- Do not teach Spark, Kafka, or a warehouse vendor. DuckDB is here because it speaks SQL in this process.
