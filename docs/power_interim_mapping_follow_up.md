# Power-interim aggregate mapping follow-up

## 2026-08-04: aggregate other-petroleum-products allocation

The 9th Outlook fuel `07_x_other_petroleum_products` is an aggregate while
the LEAP power-interim branches distinguish `07.14 Bitumen`, `07.16 Petroleum
coke`, and `07.17 Other products`.  The direct display-name path previously
resolved this aggregate as Bitumen and consequently placed the entire projected
value on the Bitumen feedstock branch.

The interim-power workflow now applies the established `01_x_thermal_coal`
method to this petroleum aggregate: allocate each projected value across its
mapped ESTO leaf products using the economy's base-year ESTO profile; if that
profile is absent, use the APEC-wide profile; if no profile exists anywhere,
split evenly.  This prevents a first-match display name from becoming an
implicit allocation rule.

## Follow-up design note

The canonical mappings already recorded the one-to-many relationship, but that
relationship was not carried through the power-interim display/export path.
This suggests that mapping semantics are currently duplicated across loaders,
projection allocation, display-name resolution, and export builders.

The mapping layer would benefit from a cleanup that makes the intended role of
each mapping explicit and modular:

- classify one-to-many mappings as either structural roll-ups or leaf-allocation
  rules;
- route every leaf-allocation rule through one shared allocation service;
- prevent display-name resolution from selecting a leaf for an aggregate code;
- add coverage that verifies the source aggregate is conserved across all
  target leaves.

Until that cleanup is complete, new aggregate fuel codes should be reviewed at
every source-to-LEAP export boundary rather than relying only on canonical
mapping-table coverage.
