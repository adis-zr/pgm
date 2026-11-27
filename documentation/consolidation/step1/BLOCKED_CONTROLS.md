# Inherited controls D1-D90: portable or blocked (no weakening, no relabeling)

Suite `code/cex/hp/check_dgp.py` run one control per subprocess with the private records root pointed at an EMPTY directory (`PGM_RECORDS_ROOT`), timeout 900 s per control, commit `ed8c676644fd`. Counts: {"BLOCKED": 51, "PORTABLE": 39}. A BLOCKED control failed while a private record input it references was absent; the dependency is named verbatim. Nothing in the suite was weakened.

| control | status | seconds | missing private dependency (first) / records constants referenced |
|---|---|---:|---|
| D1 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n12_c4_clique_two.uai |
| D2 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n12_c4_clique_half.uai |
| D3 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n12_c4_reg6_two.uai |
| D4 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n12_c2_clique_two.uai |
| D5 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D6 | PORTABLE | 4.3 |  |
| D7 | PORTABLE | 0.6 |  |
| D8 | PORTABLE | 2.1 |  |
| D9 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c2_er50_eighth.uai |
| D10 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D11 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n12_c4_clique_two.uai |
| D12 | BLOCKED | 0.2 | '/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'; RECORDS |
| D13 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D14 | PORTABLE | 0.3 |  |
| D15 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n24_c4_clique_two.uai |
| D16 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D17 | PORTABLE | 0.2 |  |
| D18 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D19 | PORTABLE | 0.2 |  |
| D20 | PORTABLE | 0.2 |  |
| D21 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D22 | PORTABLE | 0.2 |  |
| D23 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D24 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/inputs_eval/dg_n64_c4_clique_two.uai |
| D25 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D26 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D27 | PORTABLE | 0.2 |  |
| D28 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D29 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D30 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D31 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D32 | PORTABLE | 0.2 |  |
| D33 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/PRESERVATION_18_MANIFEST.json |
| D34 | PORTABLE | 0.2 |  |
| D35 | PORTABLE | 0.3 |  |
| D36 | PORTABLE | 0.2 |  |
| D37 | PORTABLE | 0.3 |  |
| D38 | PORTABLE | 0.2 |  |
| D39 | PORTABLE | 0.2 |  |
| D40 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D41 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D42 | PORTABLE | 0.3 |  |
| D43 | PORTABLE | 0.2 |  |
| D44 | PORTABLE | 0.5 |  |
| D45 | PORTABLE | 0.2 |  |
| D46 | PORTABLE | 0.2 |  |
| D47 | PORTABLE | 0.2 |  |
| D48 | PORTABLE | 0.3 |  |
| D49 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D50 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D51 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D52 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D53 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D54 | BLOCKED | 0.6 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs_mid/dg_n16_c4_clique_two.uai |
| D55 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D56 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D57 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D58 | PORTABLE | 2.1 |  |
| D59 | PORTABLE | 0.3 |  |
| D60 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D61 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D62 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n12_c4_clique_two.uai |
| D63 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D64 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D65 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D66 | BLOCKED | 0.3 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D67 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D68 | BLOCKED | 0.3 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D69 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai |
| D70 | BLOCKED | 0.3 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D71 | BLOCKED | 0.2 | '/code/runs/mdi_2026-10-28/DGP7_RESIDUAL_JOINT'; RECORDS |
| D72 | PORTABLE | 0.2 |  |
| D73 | PORTABLE | 0.2 |  |
| D74 | PORTABLE | 0.2 |  |
| D75 | PORTABLE | 0.2 |  |
| D76 | PORTABLE | 0.2 |  |
| D77 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D78 | PORTABLE | 0.3 |  |
| D79 | BLOCKED | 0.2 | $PGM_RECORDS_ROOT/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai |
| D80 | BLOCKED | 0.3 | _WEAK32 |
| D81 | PORTABLE | 0.3 |  |
| D82 | PORTABLE | 0.6 |  |
| D83 | PORTABLE | 1.8 |  |
| D84 | PORTABLE | 0.2 |  |
| D85 | PORTABLE | 0.7 |  |
| D86 | PORTABLE | 0.3 |  |
| D87 | BLOCKED | 0.3 | _WEAK32 |
| D88 | PORTABLE | 0.2 |  |
| D89 | PORTABLE | 12.3 |  |
| D90 | BLOCKED | 0.2 | _DGP9_PACKET |
