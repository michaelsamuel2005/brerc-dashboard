import type { Finding } from './findings';
import type {
  Provenance,
  ReflowReport,
  DragAlternativeReport,
  TextSpacingReport,
  SvgSpacingReport
} from './diagnostics';
import type { CellAssessment } from './mapCellTargets';
import type { Classification } from './targetSpacing';
import {
  applyLedger,
  describeBlockers,
  type LedgerApplication,
  type Resolution,
  type ResolutionScope
} from './resolutionLedger';
import { fingerprintOf } from './fingerprint';

/**
 * One self-contained accessibility evidence record.
 *
 * Automated CI and final conformance approval are deliberately separate. A browser run
 * can prove that its automated checks are green while the release remains blocked until
 * named people complete screen-reader, real-device and other manual procedures.
 */

export type GateStatus = 'pass' | 'fail' | 'not-applicable' | 'not-assessed';

export interface GateResult {
  readonly status: GateStatus;
  readonly detail: string;
}

export const MANUAL_GATE_IDS = [
  'screenReader',
  'realDeviceTouch',
  'textResize200',
  'browserZoom400',
  'contrastSweep',
  'keyboardAndFocus',
  'pointerCancellation',
  'statusAnnouncements',
  'orientation'
] as const;

export type ManualGateId = (typeof MANUAL_GATE_IDS)[number];

export interface ManualGateAttestation {
  readonly outcome: 'pass' | 'fail' | 'not-applicable';
  readonly reviewer: string;
  readonly date: string;
  readonly environment: string;
  readonly evidence: string;
}

export type ManualGateResults =
  Readonly<Partial<Record<ManualGateId, ManualGateAttestation>>>;

export interface RunContext {
  readonly branch: string;
  readonly commitSha: string;
  readonly treeClean: boolean;
  readonly dataMode: 'msw-mock' | 'live-api';
  readonly projectName: string;
  readonly browserName: string;
  readonly browserVersion: string;
  readonly engine: string;
  readonly platform: string;
  readonly viewportLabel: string;
  readonly stateLabel: string;
  readonly cameraLabel: string;
  readonly dependencyVersions: Readonly<Record<string, string>>;
  readonly inputHashes: Readonly<Record<string, string>>;
}

export interface AutomatedCheckInput {
  readonly stateEntered: boolean;
  readonly textSpacing: boolean;
  readonly svgTextSpacing: boolean | 'not-applicable';
  readonly panAlternative: boolean | 'not-applicable';
  readonly axe: boolean;
  readonly textSpacingReport?: TextSpacingReport;
  readonly svgTextSpacingReport?: SvgSpacingReport;
  readonly axeViolations?: readonly {
    readonly id: string;
    readonly impact: string | null;
    readonly description: string;
    readonly nodes: number;
  }[];
  readonly panMovements?: Readonly<Record<string, number>>;
}

export interface EvidenceBundle {
  readonly schemaVersion: 2;
  readonly runId: string;
  readonly context: RunContext;
  readonly provenance: Provenance;
  readonly reflow: ReflowReport;
  readonly dragAlternatives: DragAlternativeReport;
  readonly domTargets: {
    readonly total: number;
    readonly passed: number;
    readonly rescuedBySpacing: number;
    readonly obstacleCount: number;
  };
  readonly mapCells: {
    readonly status: CellAssessment['status'] | 'not-applicable';
    readonly reason: string | null;
    readonly cellsMeasured: number;
    readonly minWidthPx: number | null;
    readonly minHeightPx: number | null;
    readonly camera: CellAssessment['camera'];
    readonly counts: CellAssessment['counts'];
  };
  readonly findings: readonly Finding[];
  readonly automatedDiagnostics: {
    readonly textSpacing: TextSpacingReport | null;
    readonly svgTextSpacing: SvgSpacingReport | null;
    readonly axeViolations: readonly {
      readonly id: string;
      readonly impact: string | null;
      readonly description: string;
      readonly nodes: number;
    }[];
    readonly panMovements: Readonly<Record<string, number>>;
  };
  readonly ledger: LedgerApplication;
  readonly blockers: {
    readonly automated: readonly string[];
    readonly release: readonly string[];
  };
  readonly gates: {
    readonly automated: {
      readonly deterministicFindingsClear: GateResult;
      readonly reflowClean: GateResult;
      readonly tableCellsUnclipped: GateResult;
      readonly mapCollectionConclusive: GateResult;
      readonly stateEntered: GateResult;
      readonly textSpacing: GateResult;
      readonly svgTextSpacing: GateResult;
      readonly panAlternative: GateResult;
      readonly axe: GateResult;
    };
    readonly release: {
      readonly ledgerResolved: GateResult;
      readonly manual: Readonly<Record<ManualGateId, GateResult>>;
    };
  };
  /**
   * CI assertion for this run. `not-applicable` is acceptable only where the run
   * explicitly models it; `not-assessed` never passes.
   */
  readonly automatedGatesPassed: boolean;
  /** Final approval. Cannot become true until automated, ledger and manual gates pass. */
  readonly releaseGatesPassed: boolean;
}

export interface BuildEvidenceInput {
  readonly context: RunContext;
  readonly provenance: Provenance;
  readonly reflow: ReflowReport;
  readonly dragAlternatives: DragAlternativeReport;
  readonly classification: Classification;
  readonly cells: CellAssessment;
  readonly mapApplicable: boolean;
  readonly mapNotApplicableReason?: string;
  readonly automated: AutomatedCheckInput;
  readonly resolutions: readonly Resolution[];
  readonly scope: ResolutionScope;
  readonly manual?: ManualGateResults;
}

const result = (
  value: boolean | 'not-applicable' | undefined,
  passDetail: string,
  failDetail: string,
  notApplicableDetail = 'Not applicable to this state.'
): GateResult => {
  if (value === 'not-applicable') {
    return { status: 'not-applicable', detail: notApplicableDetail };
  }
  if (value === undefined) {
    return { status: 'not-assessed', detail: 'No result was supplied.' };
  }
  return value
    ? { status: 'pass', detail: passDetail }
    : { status: 'fail', detail: failDetail };
};

const passes = (gate: GateResult): boolean =>
  gate.status === 'pass' || gate.status === 'not-applicable';

const manualGate = (
  id: ManualGateId,
  attestation: ManualGateAttestation | undefined
): GateResult => {
  if (!attestation) {
    return {
      status: 'not-assessed',
      detail: `${id}: no reviewer-attested result supplied.`
    };
  }
  const suffix =
    `Reviewer: ${attestation.reviewer}; date: ${attestation.date}; ` +
    `environment: ${attestation.environment}; evidence: ${attestation.evidence}`;
  if (attestation.outcome === 'not-applicable') {
    return { status: 'not-applicable', detail: suffix };
  }
  return {
    status: attestation.outcome,
    detail: suffix
  };
};

export function buildEvidence(input: BuildEvidenceInput): EvidenceBundle {
  const findings: Finding[] = [
    ...input.classification.findings,
    ...(input.mapApplicable ? input.cells.findings : [])
  ];
  const ledger = applyLedger(findings, input.resolutions, input.scope);

  const deterministicFindings = findings.filter(
    finding => finding.severity !== 'needs-human-decision'
  );
  const mapStatus = input.mapApplicable
    ? input.cells.status
    : 'not-applicable' as const;
  const mapReason = input.mapApplicable
    ? input.cells.reason
    : input.mapNotApplicableReason ?? 'The map is intentionally absent in this state.';

  const automatedGates = {
    deterministicFindingsClear: result(
      deterministicFindings.length === 0,
      'No deterministic WCAG, project-rule or data-quality findings.',
      `${deterministicFindings.length} deterministic finding(s) remain.`
    ),
    reflowClean: result(
      input.reflow.candidates.length === 0 &&
        !input.reflow.rootHorizontalScroll &&
        !input.reflow.rootOverflowSuppressed,
      'No unexpected root/candidate horizontal overflow.',
      `candidates=${input.reflow.candidates.length}, ` +
        `rootHorizontalScroll=${String(input.reflow.rootHorizontalScroll)}, ` +
        `rootOverflowSuppressed=${String(input.reflow.rootOverflowSuppressed)}`
    ),
    tableCellsUnclipped: result(
      input.reflow.clippedTableCells.length === 0,
      'No clipped table-cell content.',
      `${input.reflow.clippedTableCells.length} clipped table cell(s).`
    ),
    mapCollectionConclusive: input.mapApplicable
      ? result(
          input.cells.status === 'measured',
          'Canonical map cells were measured conclusively.',
          `Map assessment status: ${input.cells.status} (${input.cells.reason ?? 'no reason'}).`
        )
      : result(
          'not-applicable',
          '',
          '',
          mapReason ?? 'The map is intentionally absent in this state.'
        ),
    stateEntered: result(
      input.automated.stateEntered,
      'The requested UI state was asserted before collection.',
      'The requested UI state was not confirmed.'
    ),
    textSpacing: result(
      input.automated.textSpacing,
      'HTML text-spacing diagnostic found no clipping.',
      'HTML text-spacing diagnostic found clipping.'
    ),
    svgTextSpacing: result(
      input.automated.svgTextSpacing,
      'SVG text-spacing diagnostic found no escaping text.',
      'SVG text-spacing diagnostic found escaping text.'
    ),
    panAlternative: result(
      input.automated.panAlternative,
      'Directional controls moved the map without dragging.',
      'The non-dragging map alternative failed its functional check.'
    ),
    axe: result(
      input.automated.axe,
      'Axe found no violations in the configured WCAG tags.',
      'Axe reported one or more violations.'
    )
  };

  const manual = Object.fromEntries(
    MANUAL_GATE_IDS.map(id => [id, manualGate(id, input.manual?.[id])])
  ) as unknown as Record<ManualGateId, GateResult>;

  const releaseGates = {
    ledgerResolved: result(
      ledger.ledgerResolved,
      'Every human-decision finding has a current reviewer decision.',
      'The reviewer ledger is unresolved, stale, invalid or contains a confirmed defect.'
    ),
    manual
  };

  const automatedGatesPassed = Object.values(automatedGates).every(passes);
  const releaseGatesPassed =
    automatedGatesPassed &&
    passes(releaseGates.ledgerResolved) &&
    Object.values(manual).every(passes);

  const automatedBlockers = Object.entries(automatedGates)
    .filter(([, gate]) => !passes(gate))
    .map(([name, gate]) => `${name}: ${gate.status} — ${gate.detail}`);
  const manualBlockers = Object.entries(manual)
    .filter(([, gate]) => !passes(gate))
    .map(([name, gate]) => `${name}: ${gate.status} — ${gate.detail}`);
  const ledgerBlockers = describeBlockers(ledger);

  const runId = fingerprintOf({
    commitSha: input.context.commitSha,
    projectName: input.context.projectName,
    viewport: input.context.viewportLabel,
    state: input.context.stateLabel,
    camera: input.context.cameraLabel,
    dataMode: input.context.dataMode,
    timestamp: input.provenance.timestamp
  });

  return {
    schemaVersion: 2,
    runId,
    context: input.context,
    provenance: input.provenance,
    reflow: input.reflow,
    dragAlternatives: input.dragAlternatives,
    domTargets: {
      total: input.classification.totalTargets,
      passed: input.classification.passed.length,
      rescuedBySpacing: input.classification.rescuedBySpacing.length,
      obstacleCount: input.classification.obstacleCount
    },
    mapCells: {
      status: mapStatus,
      reason: mapReason,
      cellsMeasured: input.mapApplicable ? input.cells.cellsMeasured : 0,
      minWidthPx: input.mapApplicable ? input.cells.minWidthPx : null,
      minHeightPx: input.mapApplicable ? input.cells.minHeightPx : null,
      camera: input.mapApplicable ? input.cells.camera : null,
      counts: input.cells.counts
    },
    findings,
    automatedDiagnostics: {
      textSpacing: input.automated.textSpacingReport ?? null,
      svgTextSpacing: input.automated.svgTextSpacingReport ?? null,
      axeViolations: input.automated.axeViolations ?? [],
      panMovements: input.automated.panMovements ?? {}
    },
    ledger,
    blockers: {
      automated: automatedBlockers,
      release: [...automatedBlockers, ...ledgerBlockers, ...manualBlockers]
    },
    gates: {
      automated: automatedGates,
      release: releaseGates
    },
    automatedGatesPassed,
    releaseGatesPassed
  };
}

/** Groups findings by severity for a human-readable run summary. */
export function summariseBySeverity(
  findings: readonly Finding[]
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const finding of findings) {
    out[finding.severity] = (out[finding.severity] ?? 0) + 1;
  }
  return out;
}
