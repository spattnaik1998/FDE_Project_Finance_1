# Corpus exploration: what the unstructured sources add

**documents**: 9, **tasks**: 26, **exposure_estimates**: 774, **adoption_observations**: 126, **claims**: 21

## 1. The task list (O*NET, tab-separated bulk file)

26 tasks for SOC 13-2051 (Financial and Investment Analysts). This is the unit the exposure score operates on -- before this, the prototype had no input at all.

```
task_id task_type importance relevance_pct                                                                                statement
  21579       n/a       None          None        Advise clients on aspects of capitalization, such as amounts, sources, or timing.
  21580       n/a       None          None Analyze financial or operational performance of companies facing financial difficulti...
  21581       n/a       None          None             Assess companies as investments for clients by examining company facilities.
  21582       n/a       None          None Collaborate on projects with other professionals, such as lawyers, accountants, or pu...
  21583       n/a       None          None                    Collaborate with investment bankers to attract new corporate clients.
  21584       n/a       None          None Conduct financial analyses related to investments in green construction or green retr...
  21585       n/a       None          None              Confer with clients to restructure debt, refinance debt, or raise new debt.
  21586       n/a       None          None                                             Create client presentations of plan details.
  21587       n/a       None          None Determine the prices at which securities should be syndicated and offered to the public.
  21588       n/a       None          None                                               Develop and maintain client relationships.
```

**Ratings coverage: 0/26 tasks.**

O*NET publishes **no incumbent ratings for 13-2051**. Its task list comes from analyst review rather than a worker survey, so there is no importance score and no Core/Supplemental split. Most neighbouring finance occupations *do* have ratings (Financial Quantitative Analysts 13-2099.01, Credit Analysts 13-2041, Financial Managers 11-3031), so this is specific to the occupation we picked, not to the source.

This is a real constraint on the rubric, and it has to be decided rather than absorbed: either weight all 26 tasks equally, borrow ratings from an adjacent occupation and say so, or move the target role. Quietly treating unweighted tasks as equally important would be a modelling choice disguised as a data property.

## 2. The exposure benchmark (Excel appendix)

**Financial Analysts (13-2051)**: AIOE_language_modeling = 1.273, which is the **87th percentile** of 774 occupations.

> Felten/Raj/Seamans AI Occupational Exposure, language-modelling variant. A standardised relative index, not a probability and not a percentage: higher means more exposed relative to other occupations. Values are only meaningful compared with other occupations in the same column.

Ten most exposed occupations, for context on what the index rewards:
```
soc_code                                           occupation    value
 41-9041                                        Telemarketers 1.925633
 25-1123 English Language and Literature Teachers, Postsec... 1.856860
 25-1124 Foreign Language and Literature Teachers, Postsec... 1.813892
 25-1125                      History Teachers, Postsecondary 1.813362
 25-1112                          Law Teachers, Postsecondary 1.801888
 25-1126      Philosophy and Religion Teachers, Postsecondary 1.799875
 25-1067                    Sociology Teachers, Postsecondary 1.770457
 25-1065            Political Science Teachers, Postsecondary 1.769565
 25-1111 Criminal Justice and Law Enforcement Teachers, Po... 1.754122
 19-3041                                         Sociologists 1.747498
```

Least exposed:
```
soc_code                                           occupation     value
 47-2171                   Reinforcing Iron and Rebar Workers -1.781242
 45-4021                                              Fallers -1.791424
 27-2031                                              Dancers -1.793080
 47-3011 Helpers--Brickmasons, Blockmasons, Stonemasons, a... -1.821750
 51-6021    Pressers, Textile, Garment, and Related Materials -1.853906
```

This is the number our own rubric has to be checked against. If we score financial analysts far from the 87th percentile, we need a reason better than 'our method differs'.

## 3. The adoption curve (BTOS, wide Excel, biweekly)

**Finance and insurance, firms currently using AI (BTOS Q7):**

```
period period_start  value
202524   2025-06-09   29.9
202525   2025-06-16   29.4
202526   2025-06-23   30.5
202601   2025-12-29   30.7
202613   2026-03-23   34.3
202614   2026-03-30   36.0
202615   2026-04-06   35.5
202616   2026-04-13   36.8
202617   2026-04-20   40.0
202618   2026-04-27   36.5
```

29.9% at 2025-06-09 -> 36.5% at 2026-04-27 (+6.6 points across 21 biweekly observations).

**Finance and insurance, firms expect to use AI within six months (BTOS Q24):**

```
period period_start  value
202524   2025-06-09   31.8
202525   2025-06-16   33.3
202526   2025-06-23   34.7
202601   2025-12-29   33.2
202613   2026-03-23   41.9
202614   2026-03-30   41.7
202615   2026-04-06   42.8
202616   2026-04-13   44.2
202617   2026-04-20   45.8
202618   2026-04-27   43.8
```

31.8% at 2025-06-09 -> 43.8% at 2026-04-27 (+12.0 points across 21 biweekly observations).

Set against the ABS numbers from the API layer -- 4.5% of finance firms using any AI in 2018, and 1.1% using NLP in 2020 -- this is the diffusion curve the whole lag argument was missing. The API data gives the pre-LLM baseline; this gives what happened next.

## 4. Claims with provenance (PDF)

21 verbatim quotes across 2 papers, each carrying its page number. Nothing here is paraphrased.

**exposure_share** — eloundou_gpts_are_gpts, p.1:
> Our findings reveal that around 80% of the U.S. workforce could have at least 10% of their work tasks affected by the introduction of LLMs, while approximately 19% of workers may see at least 50% of their tasks impacted.

**not_prediction** — eloundou_gpts_are_gpts, p.1:
> We do not make predictions about the development or adoption timeline of such LLMs.

**j_curve_definition** — brynjolfsson_productivity_j_curve, p.2:
> The Productivity J-Curve: How Intangibles Complement General Purpose Technologies Erik Brynjolfsson, Daniel Rock, and Chad Syverson NBER Working Paper No. 25148 October 2018, Revised January 2020 JEL No.

The second of those is the one that matters most for us. Eloundou et al. explicitly decline to forecast adoption timing -- so their exposure number cannot be used as a timetable, which is exactly the distinction our score is built around.

## 5. Provenance ledger

```
                           doc_id format    bytes       sha256
             onet_task_statements    tsv  2759559 fecdcda81a4b
                onet_task_ratings    tsv 11707887 7c37d400c0f6
             onet_occupation_data    tsv   265794 63e6029d3d30
           eloundou_gpts_are_gpts    pdf  2119311 af3edd4efc12
    felten_aioe_language_modeling   xlsx    55714 ccdd1fb916df
             felten_aioe_appendix   xlsx   170359 c123b4c64840
                    btos_national   xlsx    87218 16487a7d419f
                      btos_sector   xlsx  1499247 39dbb5a89375
brynjolfsson_productivity_j_curve    pdf   689743 8dd1bc737a5e
```

**2 source(s) carry a mirror warning** and must be spot-checked against the publisher's own copy before any customer-facing use:
- `felten_aioe_language_modeling` — MIRROR, not the publisher's own copy. Retrieved from a third-party reproducibility repository, so values must be spot-checked against the original paper before any customer-facing use.
- `felten_aioe_appendix` — MIRROR, not the publisher's own copy -- same caveat as the language-modelling file.
