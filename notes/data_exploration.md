# Data exploration: what the four APIs actually give us

19 datasets fetched from BEA, Census, FRED and BLS. Every number below is reproducible from `data/raw/` via `scripts/fetch_all.py`.

## 1. The adoption gradient (ABS 2018)

Share of employer firms reporting *any* use of each technology, by sector. The frame's claim is that the payoff lags the machine because the complementary reorganisation lags; the gap between substrate (cloud, software) and capability (AI) is where that lag lives.

```
NAICS2017                                 sector  Artificial Intelligence  Cloud-Based  Specialized Software  Robotics  Specialized Equipment  substrate_minus_ai
       51                            Information                      6.7         58.4                  59.9       2.6                   22.7                51.7
       54 Professional, scientific, and techn...                      5.6         52.7                  58.3       2.3                   15.4                47.1
       52                  Finance and insurance                      4.5         48.8                  55.2       0.8                    6.4                44.3
       55 Management of companies and enterpr...                      4.5         47.0                  50.4       8.4                   25.1                42.5
       99              Industries not classified                      3.9         11.1                  18.1       1.6                   16.2                 7.2
       53     Real estate and rental and leasing                      3.4         38.0                  40.1       0.6                    6.6                34.6
       62      Health care and social assistance                      3.3         39.3                  50.6       2.2                   31.5                36.0
    31-33                          Manufacturing                      3.0         29.1                  41.9       9.6                   39.3                26.1
       00                  Total for all sectors                      3.0         32.4                  38.3       1.9                   17.9                29.4
       61                   Educational services                      2.9         43.3                  44.3       1.1                   12.0                40.4
       22                              Utilities                      2.8         33.8                  41.2       1.7                   26.9                31.0
       56 Administrative and support and wast...                      2.7         30.1                  32.9       1.0                   16.3                27.4
    48-49         Transportation and warehousing                      2.5         24.1                  29.0       0.9                   14.5                21.6
    44-45                           Retail trade                      2.4         23.7                  30.7       1.9                   14.8                21.3
       42                        Wholesale trade                      2.2         30.7                  32.5       2.8                   15.6                28.5
       72        Accommodation and food services                      2.0         21.0                  25.4       0.8                   11.3                19.0
       21 Mining, quarrying, and oil and gas ...                      1.9         20.2                  27.8       1.8                   17.2                18.3
       81 Other services (except public admin...                      1.8         20.6                  31.6       1.2                   25.0                18.8
       23                           Construction                      1.7         22.9                  25.5       1.2                   17.3                21.2
       71    Arts, entertainment, and recreation                      1.6         32.3                  37.2       0.9                   15.7                30.7
       11 Agriculture, forestry, fishing and ...                      1.5         14.8                  19.7       1.3                   19.9                13.3
```

**Finance and insurance (NAICS 52):** AI 4.5% of firms, cloud 48.8%, specialised software 55.2%. Rank 3 of 21 sectors on AI use.

The substrate-to-capability gap is 44.3 points: the cloud was in place, the capability was not. That is the electrification pattern stated in current data.

## 2. Which AI? The 2020 decomposition

ABS 2020 splits AI into components. Natural language processing is the one that bears on analyst work, so pooling it into a single 'AI' number would hide the relevant signal.

```
                         technology  finance_pct  finance_firms  all_sectors_pct  finance_vs_all
Touchscreens for customer interface          2.8           3238              5.2            -2.4
         Voice recognition software          2.2           2579              2.0             0.2
                   Machine learning          1.9           2280              1.7             0.2
        Natural language processing          1.1           1241              0.9             0.2
                     Machine vision          0.8            946              0.9            -0.1
                 AGV or AGV systems          0.7            872              0.4             0.3
                        RFID system          0.7            771              0.9            -0.2
                  Augmented reality          0.6            722              0.5             0.1
                           Robotics          0.6            678              0.9            -0.3
  3d printing including prototyping          0.4            466              1.1            -0.7
```

**Natural language processing in finance, 2020: 1.1% of firms in use.** This is the pre-LLM baseline for the capability now aimed at drafting, summarisation and extraction work.

## 3. Substitution or augmentation, as firms reported it

The single most load-bearing number for the exposure score. Acemoglu's point is that direction is chosen, not given; here firms say which direction they chose.

The survey asks three separate questions about the effect of AI use, encoded in the item number: headcount (D01-D03), skill level (D04-D06) and STEM skills (D07-D09). They must not be pooled -- doing so mixes 'more workers' with 'more skilled workers', which are opposite answers to the exposure question.

```
NAICS2017                           sector  headcount_increased  headcount_decreased  headcount_unchanged  net_headcount  skill_increased  skill_decreased
       23                     Construction                 21.0                  0.0                 72.8           21.0             45.0              0.0
       21 Mining, quarrying, and oil an...                 21.0                  5.5                 72.8           15.5             48.3              0.0
       81 Other services (except public...                 14.4                  0.0                 76.6           14.4             37.4              1.4
       51                      Information                 20.0                  6.0                 74.0           14.0             42.2              0.2
       54 Professional, scientific, and...                 15.6                  3.6                 80.8           12.0             43.5              0.4
       56 Administrative and support an...                 18.4                  6.6                 75.1           11.8             43.4              1.7
       22                        Utilities                 11.7                  0.0                 83.1           11.7             29.9              0.0
       55 Management of companies and e...                 17.3                  7.4                 75.0            9.9             39.0              0.7
       62 Health care and social assist...                 13.7                  4.1                 82.2            9.6             37.8              2.0
       00            Total for all sectors                 15.0                  6.3                 78.8            8.7             40.9              1.8
    48-49   Transportation and warehousing                 16.8                  9.1                 74.1            7.7             36.2              1.9
       71 Arts, entertainment, and recr...                 12.7                  6.4                 81.0            6.3             30.8              0.0
       53 Real estate and rental and le...                  9.2                  3.1                 87.7            6.1             29.0              0.0
    44-45                     Retail trade                 13.6                  7.8                 78.6            5.8             39.3              3.1
       72  Accommodation and food services                 17.7                 12.6                 69.7            5.1             43.2              7.2
       42                  Wholesale trade                 13.5                  8.7                 77.8            4.8             42.0              2.6
       52            Finance and insurance                 12.5                  8.4                 79.2            4.1             47.2              1.6
    31-33                    Manufacturing                 12.5                  9.9                 77.6            2.6             41.2              2.4
       99        Industries not classified                  0.0                  0.0                 90.4            0.0             30.9              0.0
       61             Educational services                  0.0                 11.1                 79.1          -11.1             42.9              0.0
       11 Agriculture, forestry, fishin...                  0.0                 13.9                 68.1          -13.9              2.8              0.0
```

**All sectors:** 15.0% of AI-using firms reported *increasing* headcount against 6.3% reporting a *decrease*; 78.8% reported no change.

**Finance and insurance:** 12.5% increased against 8.4% decreased (net +4.1), while 47.2% reported the *skill level* of their workers rising and only 1.6% reported it falling.

That pairing is the finding worth carrying into the score. The dominant reported effect of AI use was not fewer workers but more skilled ones -- Snijders' aided expert, in survey form.

Caveats that must travel with these numbers: they cover firms that had already adopted, they count firms rather than jobs, they predate LLMs entirely, and 'AI' in 2018 meant the technologies in section 2, not generative models. They bound the prior; they do not settle it.

## 4. Does scale gate adoption? (2018)

```
 naics                       firm_size  firms_using_ai  pct_of_size_class
     0                       All firms          141731                3.0
     0         Firms with no employees            9493                3.0
     0     Firms with 1 to 9 employees           94888                2.8
     0 Firms with 10 employees or more           37349                3.5
    52                       All firms            8914                4.5
```

Across all sectors the gradient is shallow: 2.8% of firms with 1-9 employees used AI against 3.5% of firms with 10 or more. Scale mattered, but far less than the platform-advantage story would predict -- consistent with the notes' claim that machine learning arrived as a purchasable input through APIs and the cloud rather than as a capability only large firms could build.

**Limitation:** Census publishes no size breakdown for finance (NAICS 52) in this module -- only an all-firms figure. Any size-conditioned claim about finance is therefore unsupported by this source and must not be asserted.

## 5. Labour share in securities (BEA industry 523)

Compensation of employees as a percent of value added. This is the cost line the exposure score is ultimately about, and the created-versus-captured question in one series.

```
 Year   52  521CI   523  524  5415
 1998 54.9   46.2  86.0 51.5  88.0
 2001 55.6   45.0  80.1 54.5  94.8
 2004 57.0   49.1  92.7 51.0  84.9
 2007 60.0   51.6 105.0 46.8  84.1
 2010 57.7   44.7  97.6 51.7  77.1
 2013 55.6   42.9  82.1 56.4  77.1
 2016 49.8   39.9  88.5 43.6  80.1
 2019 51.5   39.1  93.4 47.3  81.6
 2022 51.5   37.6  93.7 49.0  86.3
```

**Securities (523):** compensation share of value added moved from 75.6% in 1997 to 92.0% in 2024 (+16.4 points).

Note the level: compensation exceeds 90% of value added in securities, and tops 100% in some years. That is not an error -- value added is net of intermediate inputs and absorbs trading losses, so the ratio can exceed one when industry profits collapse (2007-08 is visible). It does mean this series is a poor single-year gauge and should be read as a trend.

## 6. Churn in finance, 1978 onward (BDS)

Livermore found 40% of the 1888-1905 industrial trusts dead by the early 1930s; Caves found the survivors' average share fell from 69% to 45%. Concentration under a general purpose technology may be a transitional phase. Entry and exit rates are how we would see that.

```
 decade  entry_rate  exit_rate  reallocation    firms
   1970       11.02       6.63         19.88 149459.0
   1980       11.45       9.14         25.86 166555.4
   1990       12.41       9.82         32.63 184086.7
   2000       12.44      11.01         32.31 219195.7
   2010        8.62       8.78         24.46 211571.1
   2020        8.53       8.94         25.72 214575.0
```

Coverage: 1978-2023, 46 annual observations for NAICS 52.

## 7. Establishment size distribution, finance subsectors (CBP 2022)

```
 NAICS2017                               NAICS2017_LABEL  ESTAB     EMP    PAYANN  avg_emp_per_estab  avg_pay_per_emp_usd
       522  Credit intermediation and related activities 184808 2941404 297460150               15.9             101129.0
       524     Insurance carriers and related activities 180971 2866585 274834114               15.8              95875.0
       523 Securities, commodity contracts, and other... 112776  993866 268128663                8.8             269784.0
       521           Monetary authorities - central bank     67   21055   3006963              314.3             142815.0
       525   Funds, trusts, and other financial vehicles   1924    8987   1707092                4.7             189951.0
```

**Securities (523):** 112,776 establishments, 993,866 employees, average annual pay $269,784. That pay level is why a task-level exposure score in this occupation carries real money.

## 8. Productivity, labour share and finance employment (FRED)

Series retrieved:
```
             id                                                        title                            units frequency
         OPHNFB Nonfarm Business Sector: Labor Productivity (Output per H...                   Index 2017=100 Quarterly
    PRS85006173         Nonfarm Business Sector: Labor Share for All Workers                   Index 2017=100 Quarterly
         USFIRE                          All Employees, Financial Activities             Thousands of Persons   Monthly
  CES5552300001 All Employees, Securities, Commodity Contracts, Funds, Tr...             Thousands of Persons   Monthly
     MPU9900063                     Manufacturing Sector: Labor Productivity     Percent Change from Year Ago    Annual
Y033RC1Q027SBEA Gross Private Domestic Investment: Fixed Investment: Nonr...              Billions of Dollars Quarterly
B985RC1Q027SBEA Private fixed investment: Nonresidential: Intellectual pr...              Billions of Dollars Quarterly
          GDPC1                                  Real Gross Domestic Product Billions of Chained 2017 Dollars Quarterly
         PAYEMS                                 All Employees, Total Nonfarm             Thousands of Persons   Monthly
       COMPRNFB Nonfarm Business Sector: Real Hourly Compensation for All...                   Index 2017=100 Quarterly
```

```
      series_id first_date  last_date  first_value  last_value  n_obs  pct_change
B985RC1Q027SBEA 2015-01-01 2026-04-01      311.071     816.630     46       162.5
  CES5552300001 2015-01-01 2026-08-01      896.300    1174.400    140        31.0
       COMPRNFB 2015-01-01 2026-04-01       98.538     109.198     46        10.8
          GDPC1 2015-01-01 2026-04-01    18666.621   24269.613     46        30.0
     MPU9900063 2015-01-01 2024-01-01       -1.700      -0.700     10       -58.8
         OPHNFB 2015-01-01 2026-04-01       97.637     120.017     46        22.9
         PAYEMS 2015-01-01 2026-08-01   140568.000  159075.000    140        13.2
    PRS85006173 2015-01-01 2026-04-01       99.693      93.446     46        -6.3
         USFIRE 2015-01-01 2026-08-01     8059.000    9086.000    140        12.7
Y033RC1Q027SBEA 2015-01-01 2026-04-01     1139.214    1864.836     46        63.7
```

Since 2015. Solow's remark was that you could see the computer age everywhere but in the productivity statistics; the question this project asks is whether the same is currently true of agents, and these are the series where it would show up first.
