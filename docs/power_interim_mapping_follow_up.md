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

## 2026-08-04: human review required before Industry/non-road comparator work

Do not implement further fixes for the `All demand aggregated/Industry` or
`All demand aggregated/Transport non road` balance-review comparators until a
human has reviewed the mapping model and the intended comparison boundaries.

The active investigation exposed unresolved—and, in places, contradictory—
assumptions about the relationship between the three axes used by the review:

- LEAP branch paths, including displayed aggregate branches such as
  `All demand aggregated/Transport non road`;
- ESTO flows/products, where Mexico has real component rows such as
  `15.03 Rail / 17 Electricity` and the 2022 component sum is 5.883007 PJ;
- 9th Outlook sector/fuel codes, where `15_01,15_03-15_06 Transport non-road`
  appears in the canonical pair sheet as a valid rolled comparison identity,
  but is not a raw 9th sector code. Its components must be resolved from the
  declared rollup rules before raw-data extraction.

Recent agent work attempted to compensate for this ambiguity inside the balance
diagnostics with a direct-9th override. That work demonstrated useful symptoms
(for example, a base-year ESTO value can be incorrectly overwritten by a zero
9th value), but it is **not** a trusted design for follow-up implementation.
The agents are also confused about which mapping layer owns each relationship;
their conclusions must not be treated as authoritative mapping guidance.

Human review should establish, before any code or workbook change:

1. whether `ninth_pairs_to_esto_pairs` is strictly a real-9th-code ↔ ESTO-pair
   crosswalk, and where aggregate selector membership belongs instead;
2. the authoritative LEAP branch ↔ ESTO component mapping for all-demand
   aggregate branches;
3. how a real 9th aggregate total is allocated across multiple ESTO products,
   including the approved source of allocation shares; and
4. whether balance-review comparators should consume allocated ESTO pairs,
   explicit aggregate definitions, or another reviewed mapping artifact.

Until those decisions are recorded in the mapping documentation and tests, do
not add selector parsing, branch-specific diagnostic overrides, or inferred
mapping rules to work around the reported values.
