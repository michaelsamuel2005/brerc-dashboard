import type { TargetNode, TargetRect, GeometryConfidence } from './targetSpacing';

/**
 * Test helpers. `noUncheckedIndexedAccess` makes `array[0]` possibly-undefined, so
 * tests use `first()`/`at()` rather than non-null assertions.
 */

export function first<T>(a: readonly T[]): T {
  const v = a[0];
  if (v === undefined) throw new Error('expected at least one element');
  return v;
}

export function at<T>(a: readonly T[], i: number): T {
  const v = a[i];
  if (v === undefined) throw new Error(`expected an element at index ${i}`);
  return v;
}

export const rect = (left: number, top: number, width: number, height: number): TargetRect =>
  ({ left, top, right: left + width, bottom: top + height, width, height });

let counter = 0;
export const resetIndexes = (): void => { counter = 0; };

export interface MakeOpts {
  label?: string;
  exceptionClaim?: string | null;
  sameActionGroup?: string | null;
  geometryConfidence?: GeometryConfidence;
  index?: number;
}

export function mk(
  left: number, top: number, width: number, height: number, opts: MakeOpts = {}
): TargetNode {
  const index = opts.index ?? counter++;
  return {
    index,
    label: opts.label ?? `t${index}`,
    rect: rect(left, top, width, height),
    exceptionClaim: opts.exceptionClaim ?? null,
    sameActionGroup: opts.sameActionGroup ?? null,
    geometryConfidence: opts.geometryConfidence ?? 'verified-rectangular'
  };
}

export const kinds = (findings: readonly { kind: string }[]): string[] =>
  findings.map(f => f.kind).sort();

export const countKind = (findings: readonly { kind: string }[], kind: string): number =>
  findings.filter(f => f.kind === kind).length;
