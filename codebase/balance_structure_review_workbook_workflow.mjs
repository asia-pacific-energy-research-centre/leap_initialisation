// Build a balance-shaped diagnostic workbook from a LEAP Energy Balance export
// and the baseline-seed source-comparison diagnostics.

import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const MAIN_REPO_ROOT = "C:/Users/Work/github/leap_initialisation";
const WORKTREE_ROOT =
  `${MAIN_REPO_ROOT}/.claude/worktrees/baseline-seed-export-diagnostics`;
const ECONOMY = "01_AUS";
const SCENARIO = "Reference";
const YEAR = 2022;
const UNITS = "Petajoule";
const SOURCE_WORKBOOK = `${MAIN_REPO_ROOT}/data/leap balances exports - testing/${ECONOMY}/${YEAR}.xlsx`;
const DIAGNOSTICS_DIRECTORY =
  `${WORKTREE_ROOT}/outputs/leap_exports/supply_reconciliation/supporting_files/` +
  "baseline_seed_balance_diagnostics/01_AUS_2022_POST_EFF_FIX_20260728";
const OUTPUT_WORKBOOK =
  `${MAIN_REPO_ROOT}/outputs/leap_exports/supply_reconciliation/supporting_files/` +
  "baseline_seed_balance_diagnostics/01_AUS_2022_POST_EFF_FIX_20260728/" +
  "aus_2022_balance_structure_review_v2.xlsx";
const TEMP_DIRECTORY =
  `${WORKTREE_ROOT}/.tmp/aus_balance_review`;

const SOURCE_SHEET_NAME = "Energy Balance";
const LEAP_SHEET_NAME = "LEAP Values";
const ERROR_SHEET_NAME = "LEAP - Source Error";
const CORRECT_SHEET_NAME = "Correct Source Values";
const FULL_EXPECTED_SHEET_NAME = "Full Expected Source";
const MISSING_SHEET_NAME = "Missing Combinations";

const RED_FONT = "#9C0006";
const RED_FILL = "#FCE8E6";
const BLUE_FONT = "#1F4E78";
const BLUE_FILL = "#DDEBF7";
const YELLOW_FILL = "#FFF2CC";
const PALE_RED_FILL = "#F4CCCC";
const NEUTRAL_FILL = "#F2F2F2";
const HEADER_FILL = "#1F4E78";
const HEADER_FONT = "#FFFFFF";
const SUBHEADER_FILL = "#D9EAF7";
const PJ_NUMBER_FORMAT = "#,##0.00;-#,##0.00;-";

function normalizeLabel(value) {
  return String(value ?? "").trim();
}

function rowsFromValues(values) {
  const headers = values[0].map((value) => String(value ?? ""));
  return values.slice(1).map((row) =>
    Object.fromEntries(headers.map((header, index) => [header, row[index]])),
  );
}

function asNumber(value) {
  if (value === "" || value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function columnName(columnIndexZeroBased) {
  let value = columnIndexZeroBased + 1;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function cellAddress(rowIndexZeroBased, columnIndexZeroBased) {
  return `${columnName(columnIndexZeroBased)}${rowIndexZeroBased + 1}`;
}

function countBy(rows, field) {
  const result = {};
  for (const row of rows) {
    const key = String(row[field] ?? "");
    result[key] = (result[key] ?? 0) + 1;
  }
  return result;
}

async function readCsvRows(csvPath, sheetName) {
  const text = await fs.readFile(csvPath, "utf8");
  const csvWorkbook = await Workbook.fromCSV(text, { sheetName });
  const values = csvWorkbook.worksheets.getItem(sheetName).getUsedRange().values;
  return rowsFromValues(values);
}

function makeStructureResolver(sourceValues) {
  const rowIndex = new Map();
  for (let row = 3; row < sourceValues.length; row += 1) {
    const normalized = normalizeLabel(sourceValues[row][0]);
    if (!rowIndex.has(normalized)) {
      rowIndex.set(normalized, []);
    }
    rowIndex.get(normalized).push(row);
  }

  const fuelIndex = new Map();
  for (let column = 1; column < sourceValues[2].length; column += 1) {
    const normalized = normalizeLabel(sourceValues[2][column]);
    if (!fuelIndex.has(normalized)) {
      fuelIndex.set(normalized, []);
    }
    fuelIndex.get(normalized).push(column);
  }

  function resolveRow(label) {
    const rawLabel = String(label ?? "");
    const exactCandidates = rowIndex.get(normalizeLabel(rawLabel)) ?? [];
    if (exactCandidates.length === 1) {
      return { candidates: exactCandidates, mode: "exact_visible_label" };
    }
    if (exactCandidates.length > 1) {
      return { candidates: exactCandidates, mode: "ambiguous_visible_label" };
    }

    // Diagnostic hierarchy paths use "/" while the visible balance exposes
    // only the leaf label. A leading-space indent identifies a child row. This
    // resolves X/X transformation paths without choosing silently between the
    // identically named parent and child rows.
    const pathParts = rawLabel.split("/").map(normalizeLabel).filter(Boolean);
    if (pathParts.length > 1) {
      const leafCandidates = rowIndex.get(pathParts.at(-1)) ?? [];
      const indentedCandidates = leafCandidates.filter((row) =>
        /^\s+/.test(String(sourceValues[row][0] ?? "")),
      );
      if (indentedCandidates.length === 1) {
        return { candidates: indentedCandidates, mode: "hierarchy_leaf_indent" };
      }
      return {
        candidates: leafCandidates,
        mode: leafCandidates.length === 0 ? "absent" : "ambiguous_hierarchy_leaf",
      };
    }
    return { candidates: [], mode: "absent" };
  }

  function resolve(rowLabel, fuelLabel) {
    const rowResult = resolveRow(rowLabel);
    const fuelCandidates = fuelIndex.get(normalizeLabel(fuelLabel)) ?? [];
    const candidateCount = rowResult.candidates.length * fuelCandidates.length;
    if (candidateCount === 1) {
      return {
        row: rowResult.candidates[0],
        column: fuelCandidates[0],
        candidateCount,
        status: "unique",
        mode: rowResult.mode,
      };
    }
    return {
      row: null,
      column: null,
      candidateCount,
      status: candidateCount === 0 ? "absent" : "ambiguous",
      mode: rowResult.mode,
    };
  }

  return { resolve };
}

function preferredComparisonLabels(row) {
  return {
    rowLabel: row.leap_balance_row || row.leap_sector_names,
    fuelLabel: row.leap_balance_fuel || row.leap_fuel_names,
  };
}

function preferredMappingIssueLabels(row) {
  return {
    rowLabel: row.leap_flow_name || row.leap_flow || row.leap_sector_name_full_path,
    fuelLabel: row.leap_product_name || row.leap_product,
  };
}

function copyBalanceLayout(sourceSheet, destinationSheet, sourceRows, sourceColumns) {
  const sourceRange = sourceSheet.getRangeByIndexes(0, 0, sourceRows, sourceColumns);
  const destinationRange = destinationSheet.getRangeByIndexes(
    0,
    0,
    sourceRows,
    sourceColumns,
  );
  destinationRange.copyFrom(sourceRange, "all");

  for (let column = 0; column < sourceColumns; column += 1) {
    const width = sourceSheet
      .getRangeByIndexes(0, column, sourceRows, 1)
      .format.columnWidthPx;
    if (width) {
      destinationSheet
        .getRangeByIndexes(0, column, sourceRows, 1)
        .format.columnWidthPx = width;
    }
  }
  destinationSheet.showGridLines = sourceSheet.showGridLines;
  destinationSheet.freezePanes.freezeRows(3);
  destinationSheet.freezePanes.freezeColumns(1);
}

function setDiagnosticTitle(sheet, title, explanation) {
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A2").values = [[explanation]];
  sheet.getRange("A1").format.font = { bold: true, color: "#1F1F1F" };
  sheet.getRange("A2").format.font = { italic: true, color: "#595959" };
}

function styleCell(cell, fill, fontColor, bold = false) {
  cell.format.fill = fill;
  cell.format.font = { color: fontColor, bold };
  cell.format.numberFormat = PJ_NUMBER_FORMAT;
}

function makeMissingRecord({
  category,
  economy,
  scenario,
  year,
  rowLabel,
  fuelLabel,
  leapValue,
  status,
  details,
  resolution,
  recommendation,
}) {
  return [
    category,
    economy,
    scenario,
    asNumber(year) ?? year,
    rowLabel,
    fuelLabel,
    asNumber(leapValue),
    status,
    details,
    resolution.status === "unique"
      ? "Yes"
      : resolution.status === "ambiguous"
        ? "Ambiguous"
        : "No",
    resolution.candidateCount,
    resolution.status === "unique"
      ? cellAddress(resolution.row, resolution.column)
      : "",
    resolution.mode,
    recommendation,
  ];
}

async function buildBalanceStructureReviewWorkbook(config = {}) {
  const sourceWorkbookPath = config.sourceWorkbook ?? SOURCE_WORKBOOK;
  const diagnosticsDirectory = config.diagnosticsDirectory ?? DIAGNOSTICS_DIRECTORY;
  const outputWorkbookPath = config.outputWorkbook ?? OUTPUT_WORKBOOK;
  const tempDirectory = config.tempDirectory ?? TEMP_DIRECTORY;

  const sourceBefore = await fs.readFile(sourceWorkbookPath);
  const sourceBlob = await FileBlob.load(sourceWorkbookPath);
  const workbook = await SpreadsheetFile.importXlsx(sourceBlob);
  const sourceSheet = workbook.worksheets.getItem(SOURCE_SHEET_NAME);
  const sourceUsedRange = sourceSheet.getUsedRange();
  const sourceValues = sourceUsedRange.values;
  const sourceRows = sourceValues.length;
  const sourceColumns = sourceValues[0].length;

  const title = String(sourceValues[0][0] ?? "");
  const metadata = String(sourceValues[1][0] ?? "");
  if (!/AUS/i.test(title)) {
    throw new Error(`Source area metadata does not identify AUS: ${title}`);
  }
  if (!metadata.includes(`Scenario: ${SCENARIO}`)) {
    throw new Error(`Source scenario metadata is not ${SCENARIO}: ${metadata}`);
  }
  if (!metadata.includes(`Year: ${YEAR}`)) {
    throw new Error(`Source year metadata is not ${YEAR}: ${metadata}`);
  }
  if (!metadata.includes(`Units: ${UNITS}`)) {
    throw new Error(`Source units metadata is not ${UNITS}: ${metadata}`);
  }
  if (sourceRows !== 138 || sourceColumns !== 39) {
    throw new Error(`Expected a 138x39 balance structure, found ${sourceRows}x${sourceColumns}`);
  }

  const differences = await readCsvRows(
    path.join(diagnosticsDirectory, "leap_balance_source_differences.csv"),
    "Differences",
  );
  const reviews = await readCsvRows(
    path.join(diagnosticsDirectory, "leap_balance_source_review.csv"),
    "Review",
  );
  const mappingIssues = await readCsvRows(
    path.join(diagnosticsDirectory, "leap_balance_mapping_issues.csv"),
    "MappingIssues",
  );

  if (differences.length !== 195 || reviews.length !== 195) {
    throw new Error(
      `Expected 195 comparison rows, found ${differences.length} differences and ${reviews.length} review rows`,
    );
  }
  const comparisonIdentityFields = [
    "economy",
    "scenario",
    "year",
    "esto_flow",
    "esto_product",
    "leap_sector_names",
    "leap_fuel_names",
    "status",
    "difference_pj",
  ];
  for (let index = 0; index < differences.length; index += 1) {
    for (const field of comparisonIdentityFields) {
      if (String(differences[index][field] ?? "") !== String(reviews[index][field] ?? "")) {
        throw new Error(
          `Differences/review comparison row ${index + 1} disagrees on ${field}`,
        );
      }
    }
  }
  const statusCounts = countBy(reviews, "status");
  const issueCounts = countBy(mappingIssues, "reason");
  const expectedCounts = {
    reference_unavailable: 37,
    missing_esto_pair: 149,
    total_balance_mapping_check: 3,
  };
  for (const [key, expected] of Object.entries(expectedCounts)) {
    const actual = statusCounts[key] ?? issueCounts[key] ?? 0;
    if (actual !== expected) {
      throw new Error(`Expected ${expected} ${key} rows, found ${actual}`);
    }
  }
  if (mappingIssues.length !== 152) {
    throw new Error(`Expected 152 mapping/check rows, found ${mappingIssues.length}`);
  }

  sourceSheet.name = LEAP_SHEET_NAME;
  sourceSheet.freezePanes.freezeRows(3);
  sourceSheet.freezePanes.freezeColumns(1);
  const errorSheet = workbook.worksheets.add(ERROR_SHEET_NAME);
  const correctSheet = workbook.worksheets.add(CORRECT_SHEET_NAME);
  const fullExpectedSheet = workbook.worksheets.add(FULL_EXPECTED_SHEET_NAME);
  const missingSheet = workbook.worksheets.add(MISSING_SHEET_NAME);

  copyBalanceLayout(sourceSheet, errorSheet, sourceRows, sourceColumns);
  copyBalanceLayout(sourceSheet, correctSheet, sourceRows, sourceColumns);
  copyBalanceLayout(sourceSheet, fullExpectedSheet, sourceRows, sourceColumns);
  errorSheet.getRangeByIndexes(3, 1, sourceRows - 3, sourceColumns - 1).clear({
    applyTo: "contents",
  });
  correctSheet.getRangeByIndexes(3, 1, sourceRows - 3, sourceColumns - 1).clear({
    applyTo: "contents",
  });
  fullExpectedSheet.getRangeByIndexes(3, 1, sourceRows - 3, sourceColumns - 1).clear({
    applyTo: "contents",
  });
  fullExpectedSheet.getRangeByIndexes(
    3,
    1,
    sourceRows - 3,
    sourceColumns - 1,
  ).format.fill = NEUTRAL_FILL;
  setDiagnosticTitle(
    errorSheet,
    `LEAP - Source Error for Area "${ECONOMY}"`,
    `Scenario: ${SCENARIO}, Year: ${YEAR}, Units: ${UNITS} | Red = LEAP minus source; yellow blank = no safe comparator`,
  );
  setDiagnosticTitle(
    correctSheet,
    `Correct Source Values for Area "${ECONOMY}"`,
    `Scenario: ${SCENARIO}, Year: ${YEAR}, Units: ${UNITS} | Blue = source value; yellow blank = no safe comparator`,
  );
  setDiagnosticTitle(
    fullExpectedSheet,
    `Full Expected Source for Area "${ECONOMY}"`,
    `Scenario: ${SCENARIO}, Year: ${YEAR}, Units: ${UNITS} | Blue = source-backed expected value; yellow = known comparator unavailable; grey = structurally absent or not comparable`,
  );

  const resolver = makeStructureResolver(sourceValues);
  const missingRecords = [];
  const comparisonStateCounts = {
    mapped: 0,
    reference_unavailable: 0,
    missing_visible_structure: 0,
    ambiguous_structure_resolution: 0,
  };
  const populatedKeys = new Set();
  const yellowKeys = new Set();
  const reconciliationSamples = [];

  for (const review of reviews) {
    const labels = preferredComparisonLabels(review);
    const resolution = resolver.resolve(labels.rowLabel, labels.fuelLabel);

    if (review.status === "reference_unavailable") {
      comparisonStateCounts.reference_unavailable += 1;
      missingRecords.push(
        makeMissingRecord({
          category: "reference_unavailable",
          economy: review.economy,
          scenario: review.scenario,
          year: review.year,
          rowLabel: labels.rowLabel,
          fuelLabel: labels.fuelLabel,
          leapValue: review.leap_value_pj,
          status: review.status,
          details: review.evidence_note || "No valid raw source comparator is available.",
          resolution,
          recommendation: "Leave diagnostic cells blank; do not interpret unavailable as zero.",
        }),
      );
      if (resolution.status === "unique") {
        yellowKeys.add(`${resolution.row},${resolution.column}`);
      }
      continue;
    }

    if (resolution.status !== "unique") {
      const state =
        resolution.status === "ambiguous"
          ? "ambiguous_structure_resolution"
          : "missing_visible_structure";
      comparisonStateCounts[state] += 1;
      missingRecords.push(
        makeMissingRecord({
          category: "structure_unresolved",
          economy: review.economy,
          scenario: review.scenario,
          year: review.year,
          rowLabel: labels.rowLabel,
          fuelLabel: labels.fuelLabel,
          leapValue: review.leap_value_pj,
          status: state,
          details: `Diagnostic comparator could not resolve to exactly one visible balance cell (${resolution.mode}).`,
          resolution,
          recommendation: "Review the balance row naming/structure; do not allocate the difference.",
        }),
      );
      continue;
    }

    comparisonStateCounts.mapped += 1;
    const key = `${resolution.row},${resolution.column}`;
    if (populatedKeys.has(key)) {
      throw new Error(`Multiple comparable diagnostics resolve to ${cellAddress(resolution.row, resolution.column)}`);
    }
    populatedKeys.add(key);

    const address = cellAddress(resolution.row, resolution.column);
    const errorCell = errorSheet.getRange(address);
    const correctCell = correctSheet.getRange(address);
    const fullExpectedCell = fullExpectedSheet.getRange(address);
    const leapValue = asNumber(review.leap_value_pj);
    const sourceValue = asNumber(review.source_value_pj);
    const reportedDifference = asNumber(review.difference_pj);
    const displayedError = review.status === "match" ? 0 : reportedDifference;

    errorCell.values = [[displayedError]];
    if (review.status === "value_mismatch") {
      styleCell(errorCell, RED_FILL, RED_FONT, true);
      correctCell.formulas = [
        [`='${LEAP_SHEET_NAME}'!${address}-'${ERROR_SHEET_NAME}'!${address}`],
      ];
      fullExpectedCell.formulas = [
        [`='${LEAP_SHEET_NAME}'!${address}-'${ERROR_SHEET_NAME}'!${address}`],
      ];
    } else {
      styleCell(errorCell, NEUTRAL_FILL, "#666666", false);
      // Match errors intentionally display as zero. Preserve the exact source
      // value numerically so micro-PJ within-tolerance differences are not lost.
      correctCell.values = [[sourceValue]];
      fullExpectedCell.values = [[sourceValue]];
    }
    styleCell(correctCell, BLUE_FILL, BLUE_FONT, false);
    styleCell(fullExpectedCell, BLUE_FILL, BLUE_FONT, false);

    if (
      reconciliationSamples.length < 50 &&
      leapValue !== null &&
      sourceValue !== null &&
      displayedError !== null
    ) {
      reconciliationSamples.push({
        owner: review.preliminary_owner,
        row: labels.rowLabel,
        fuel: labels.fuelLabel,
        address,
        status: review.status,
        leapValue,
        displayedError,
        sourceValue,
      });
    }
  }

  for (const issue of mappingIssues) {
    const labels = preferredMappingIssueLabels(issue);
    const resolution = resolver.resolve(labels.rowLabel, labels.fuelLabel);
    const isBoundary = issue.reason === "total_balance_mapping_check";
    missingRecords.push(
      makeMissingRecord({
        category: isBoundary ? "aggregate_boundary_error" : "missing_esto_pair",
        economy: issue.economy || ECONOMY,
        scenario: issue.scenario || SCENARIO,
        year: issue.year || YEAR,
        rowLabel: labels.rowLabel,
        fuelLabel: labels.fuelLabel,
        leapValue: issue.value_petajoule,
        status: issue.reason,
        details: issue.details,
        resolution,
        recommendation: isBoundary
          ? "Treat as an aggregate comparison-boundary error, not an ordinary cell mapping."
          : "Add or review the explicit LEAP-to-ESTO pair before using this cell as a comparator.",
      }),
    );
    if (!isBoundary && resolution.status === "unique") {
      yellowKeys.add(`${resolution.row},${resolution.column}`);
    }
  }

  for (const key of yellowKeys) {
    const [row, column] = key.split(",").map(Number);
    const address = cellAddress(row, column);
    errorSheet.getRange(address).clear({ applyTo: "contents" });
    correctSheet.getRange(address).clear({ applyTo: "contents" });
    fullExpectedSheet.getRange(address).clear({ applyTo: "contents" });
    errorSheet.getRange(address).format.fill = YELLOW_FILL;
    correctSheet.getRange(address).format.fill = YELLOW_FILL;
    fullExpectedSheet.getRange(address).format.fill = YELLOW_FILL;
  }

  const accountedComparisonRows = Object.values(comparisonStateCounts).reduce(
    (sum, value) => sum + value,
    0,
  );
  if (accountedComparisonRows !== reviews.length) {
    throw new Error(
      `Comparison audit lost rows: accounted for ${accountedComparisonRows} of ${reviews.length}`,
    );
  }
  if (missingRecords.length !== 37 + 24 + 152) {
    throw new Error(`Expected 213 missing/audit records, found ${missingRecords.length}`);
  }

  const missingHeaders = [
    "Category",
    "Economy",
    "Scenario",
    "Year",
    "LEAP balance row",
    "LEAP fuel",
    "LEAP value (PJ)",
    "Diagnostic/source status",
    "Reason/details",
    "Present in visible structure",
    "Candidate cell count",
    "Intended cell address",
    "Structure resolution status",
    "Recommended interpretation",
  ];
  missingSheet.showGridLines = false;
  missingSheet.getRange("A1:N1").merge();
  missingSheet.getRange("A1").values = [["AUS 2022 Balance Diagnostic - Missing and Unavailable Combinations"]];
  missingSheet.getRange("A1:N1").format = {
    fill: HEADER_FILL,
    font: { bold: true, color: HEADER_FONT, size: 14 },
  };
  missingSheet.getRange("A2:N2").merge();
  missingSheet.getRange("A2").values = [[
    "Diagnostic view only. Red = LEAP minus source mismatch; blue = correct source; yellow blank = no safe comparator; uncoloured/zero = within tolerance.",
  ]];
  missingSheet.getRange("A2:N2").format = {
    fill: SUBHEADER_FILL,
    font: { color: "#1F1F1F", italic: true },
  };
  const summary = [
    ["Comparison rows", reviews.length, "Mapped comparable rows", comparisonStateCounts.mapped],
    ["Mismatches", statusCounts.value_mismatch, "Matches", statusCounts.match],
    ["Reference unavailable", statusCounts.reference_unavailable, "Structure absent", comparisonStateCounts.missing_visible_structure],
    ["Mapping/check issue rows", mappingIssues.length, "Missing ESTO pair", issueCounts.missing_esto_pair],
    ["Total-balance boundary errors", issueCounts.total_balance_mapping_check, "Ambiguous structure", comparisonStateCounts.ambiguous_structure_resolution],
  ];
  missingSheet.getRange("A4:D8").values = summary;
  missingSheet.getRange("A4:D8").format.borders = {
    preset: "all",
    style: "thin",
    color: "#B4C6E7",
  };
  missingSheet.getRange("A4:A8").format.font = { bold: true, color: "#1F4E78" };
  missingSheet.getRange("C4:C8").format.font = { bold: true, color: "#1F4E78" };
  missingSheet.getRange("B4:B8").format.numberFormat = "#,##0";
  missingSheet.getRange("D4:D8").format.numberFormat = "#,##0";

  const headerRow = 10;
  const firstDataRow = headerRow + 1;
  const lastDataRow = headerRow + missingRecords.length;
  missingSheet.getRange(`A${headerRow}:N${headerRow}`).values = [missingHeaders];
  missingSheet.getRange(`A${firstDataRow}:N${lastDataRow}`).values = missingRecords;
  missingSheet.getRange(`A${headerRow}:N${headerRow}`).format = {
    fill: HEADER_FILL,
    font: { bold: true, color: HEADER_FONT },
    wrapText: true,
    verticalAlignment: "center",
  };
  missingSheet.getRange(`A${firstDataRow}:N${lastDataRow}`).format = {
    verticalAlignment: "top",
    wrapText: true,
  };
  missingSheet.getRange(`D${firstDataRow}:D${lastDataRow}`).format.numberFormat = "0";
  missingSheet.getRange(`G${firstDataRow}:G${lastDataRow}`).format.numberFormat =
    PJ_NUMBER_FORMAT;
  missingSheet.getRange(`K${firstDataRow}:K${lastDataRow}`).format.numberFormat = "0";
  missingSheet.getRange(`A${firstDataRow}:N${lastDataRow}`).format.borders = {
    insideHorizontal: { style: "thin", color: "#E7E6E6" },
    bottom: { style: "thin", color: "#BFBFBF" },
  };
  for (let index = 0; index < missingRecords.length; index += 1) {
    const excelRow = firstDataRow + index;
    const category = missingRecords[index][0];
    missingSheet.getRange(`A${excelRow}:N${excelRow}`).format.fill =
      category === "aggregate_boundary_error" ? PALE_RED_FILL : YELLOW_FILL;
  }
  const widths = [145, 80, 85, 55, 220, 160, 95, 150, 330, 110, 90, 105, 140, 300];
  for (let column = 0; column < widths.length; column += 1) {
    missingSheet
      .getRangeByIndexes(0, column, lastDataRow, 1)
      .format.columnWidthPx = widths[column];
  }
  missingSheet.getRange(`A${headerRow}:N${headerRow}`).format.rowHeightPx = 36;
  missingSheet.freezePanes.freezeRows(headerRow);

  const missingTable = missingSheet.tables.add(
    `A${headerRow}:N${lastDataRow}`,
    true,
    "MissingCombinationsTable",
  );
  missingTable.style = "TableStyleMedium2";
  missingTable.showFilterButton = true;
  missingTable.showBandedRows = false;

  await fs.mkdir(path.dirname(outputWorkbookPath), { recursive: true });
  await fs.mkdir(tempDirectory, { recursive: true });

  const outputBlob = await SpreadsheetFile.exportXlsx(workbook);
  await outputBlob.save(outputWorkbookPath);

  const renders = {};
  for (const sheetName of [
    LEAP_SHEET_NAME,
    ERROR_SHEET_NAME,
    CORRECT_SHEET_NAME,
    FULL_EXPECTED_SHEET_NAME,
    MISSING_SHEET_NAME,
  ]) {
    const range =
      sheetName === MISSING_SHEET_NAME ? `A1:N${lastDataRow}` : "A1:AM138";
    const rendered = await workbook.render({
      sheetName,
      range,
      scale: sheetName === MISSING_SHEET_NAME ? 0.8 : 0.7,
      format: "png",
    });
    const renderPath = path.join(
      tempDirectory,
      `${sheetName.toLowerCase().replaceAll(" ", "_").replaceAll("-", "")}.png`,
    );
    await fs.writeFile(renderPath, new Uint8Array(await rendered.arrayBuffer()));
    renders[sheetName] = renderPath;
  }
  for (const [name, range] of Object.entries({
    supply: "A1:AM8",
    transformation: "A23:AM27",
    own_use: "A57:AM66",
  })) {
    const rendered = await workbook.render({
      sheetName: ERROR_SHEET_NAME,
      range,
      scale: 1.25,
      format: "png",
    });
    const renderPath = path.join(tempDirectory, `error_${name}.png`);
    await fs.writeFile(renderPath, new Uint8Array(await rendered.arrayBuffer()));
    renders[`error_${name}`] = renderPath;
  }

  const formulaErrorPattern = /#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/i;
  const formulaErrorCells = [];
  for (const sheetName of [
    ERROR_SHEET_NAME,
    CORRECT_SHEET_NAME,
    FULL_EXPECTED_SHEET_NAME,
  ]) {
    const sheet = workbook.worksheets.getItem(sheetName);
    const values = sheet.getUsedRange().values;
    const formulas = sheet.getUsedRange().formulas;
    for (let row = 0; row < values.length; row += 1) {
      for (let column = 0; column < values[row].length; column += 1) {
        const value = String(values[row][column] ?? "");
        const formula = String(formulas[row]?.[column] ?? "");
        if (formulaErrorPattern.test(value) || formulaErrorPattern.test(formula)) {
          formulaErrorCells.push(`${sheetName}!${cellAddress(row, column)}`);
        }
      }
    }
  }
  if (formulaErrorCells.length > 0) {
    throw new Error(`Formula errors found: ${formulaErrorCells.join(", ")}`);
  }

  const sourceAfter = await fs.readFile(sourceWorkbookPath);
  if (!sourceBefore.equals(sourceAfter)) {
    throw new Error("Source workbook changed during build");
  }

  const result = {
    sourceWorkbook: sourceWorkbookPath,
    outputWorkbook: outputWorkbookPath,
    metadata: { title, scenario: SCENARIO, year: YEAR, units: UNITS },
    sourceShape: { rows: sourceRows, columns: sourceColumns },
    statusCounts,
    issueCounts,
    comparisonStateCounts,
    missingAuditRows: missingRecords.length,
    formulaErrorCells,
    formulaPolicy:
      "Mismatch source values use LEAP-minus-error formulas; match source values are numeric because the error sheet intentionally displays within-tolerance differences as zero.",
    reconciliationSamples,
    renders,
  };
  await fs.writeFile(
    path.join(tempDirectory, "build_summary.json"),
    JSON.stringify(result, null, 2),
    "utf8",
  );
  return result;
}

const buildResult = await buildBalanceStructureReviewWorkbook();
console.log(JSON.stringify(buildResult, null, 2));

export { buildBalanceStructureReviewWorkbook };
