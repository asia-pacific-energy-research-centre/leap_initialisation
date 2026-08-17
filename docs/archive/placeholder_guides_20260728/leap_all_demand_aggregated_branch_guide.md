# LEAP branch creation guide: All demand aggregated

This is a LEAP structure handoff only. Create the branch paths below in every
economy area. Do not enter data or expressions as part of this task.

## Branches to create

Create these six branches directly under `Demand\All demand aggregated`:

- `Demand\All demand aggregated\Road`
- `Demand\All demand aggregated\Transport non road`
- `Demand\All demand aggregated\International transport`
- `Demand\All demand aggregated\Industry`
- `Demand\All demand aggregated\Other sector`
- `Demand\All demand aggregated\Buildings`

Under each sector branch, create the fuel leaves listed in
`leap_all_demand_aggregated_fuels_by_sector.csv` (generated evidence not retained
with this archived guide).
The CSV includes the complete LEAP path for every fuel leaf.

## Important naming rules

- Use the spellings shown in the CSV exactly: `Road`, `Transport non road`,
  and `International transport`.
- Create each fuel as a direct child of its sector branch.
- Keep `Demand\All demand aggregated` as the existing aggregate branch; do not
  move or delete it.
- Do not create extra aggregate fuel branches such as `Coal`, `Gas`, or
  `Biomass`.
- This handoff covers branch creation only. Expressions, scenarios, and data
  population are handled separately.

## Fuel-count check

| LEAP sector branch | Fuel leaves |
|---|---:|
| Road | 9 |
| Transport non road | 26 |
| International transport | 15 |
| Industry | 49 |
| Other sector | 33 |
| Buildings | 37 |
| **Total branch/fuel rows** | **169** |

The CSV is the current structural handoff. The all-economy source-data and
mapping-system audit is a separate task and must be completed before treating
this list as the final generated branch catalogue.
