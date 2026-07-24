# Colleague introduction: All demand aggregated

## What this project is

LEAP is the model where the energy-demand branches are created. The wider
project then connects those LEAP branches to two comparison sources:

- **ESTO**, the historical energy-balance data.
- **9th Outlook**, the projected energy-demand data.

The mapping system in the sibling `leap_mappings` repository maintains those
connections. You do not need to work with ESTO, 9th Outlook, or the mapping
workbooks for this LEAP structure task.

## The structure to create

The existing `All demand aggregated` branch is a container. Create the six
sector branches inside it, and create the listed fuel leaves inside each
sector branch:

```text
Demand
└── All demand aggregated
    ├── Freight road
    │   └── fuel leaves from the CSV
    ├── Passenger road
    │   └── fuel leaves from the CSV
    ├── Transport non road
    │   └── fuel leaves from the CSV
    ├── Industry
    │   └── fuel leaves from the CSV
    ├── Other sector
    │   └── fuel leaves from the CSV
    └── Buildings
        └── fuel leaves from the CSV
```

The exact full paths are in
[leap_all_demand_aggregated_fuels_by_sector.csv](<C:\Users\Work\github\leap_initialisation\docs\leap_all_demand_aggregated_fuels_by_sector.csv>).

## What you need to do in LEAP

1. Open the relevant economy area.
2. Create the six sector branches under `Demand\All demand aggregated`.
3. Create each fuel leaf as a direct child of the correct sector branch.
4. Use the CSV spellings exactly, including `Transport non road`.
5. Do not enter data, expressions, scenarios, or formulas as part of this
   structure handoff.

After the LEAP structure is updated, the model export will be refreshed and the
mapping system will use the new paths for the source-data connections.
