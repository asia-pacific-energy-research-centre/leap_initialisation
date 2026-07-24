# LEAP branch creation guide: All demand aggregated

This is a LEAP structure handoff only. Create the branch paths below in every
economy area. Do not enter data or expressions as part of this task.

## Branches to create

Create these six branches directly under `Demand`:

- `Demand\Freight road`
- `Demand\Passenger road`
- `Demand\Transport non-road`
- `Demand\Industry`
- `Demand\Other sector`
- `Demand\Buildings`

Under each sector branch, create the fuel leaves listed in
[leap_all_demand_aggregated_fuels_by_sector.csv](<C:\Users\Work\github\leap_initialisation\docs\leap_all_demand_aggregated_fuels_by_sector.csv>).
The CSV includes the complete LEAP path for every fuel leaf.

## Important naming rules

- Use the spellings and hyphenation shown in the CSV exactly.
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
| Freight road | 9 |
| Passenger road | 9 |
| Transport non-road | 26 |
| Industry | 49 |
| Other sector | 33 |
| Buildings | 37 |
| **Total branch/fuel rows** | **163** |

The 163 requested fuel names were checked against the existing direct fuel
leaves below `Demand\All demand aggregated` in both the `20_USA` and `12_NZ`
LEAP templates. All were present; no missing fuel names were found.
